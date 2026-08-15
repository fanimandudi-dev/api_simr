"""
dbscan.py — Détection spatiale de foyers épidémiques (DBSCAN) — VERSION OPTIMISÉE
=================================================================================
Appelé par le CRON APScheduler (toutes les 30 min) et par /api/admin/trigger-dbscan.

OPTIMISATIONS / CORRECTIONS :
 1. ✅ POOL DE CONNEXIONS (db.py) : fini le psycopg2.connect() à chaque exécution.
       La connexion est EMPRUNTÉE au pool (thread-safe → compatible avec le CRON)
       et TOUJOURS RENDUE via put_conn() — on ne la ferme JAMAIS (conn.close()
       détruirait une connexion du pool).
 2. ✅ 1 SEULE TRANSACTION pour toute l'analyse : extraction + écritures +
       notifications commitées ensemble (ou rollback complet en cas d'erreur).
 3. ✅ PLUS DE N+1 : le rattachement des cas au foyer se fait en 1 SEULE requête
       (unnest) au lieu d'une boucle d'INSERT par cas.
 4. ✅ DISTANCES VECTORISÉES (numpy) : matrice n×n haversine sans boucle Python,
       DBSCAN en metric='precomputed' (le rayon de 450 m est utilisé tel quel,
       plus fiable que le raccord 'haversine' de sklearn).
 5. ✅ FUSION DE FOYERS GÉRÉE : le groupe est rattaché au foyer existant
       DOMINANT (celui qui partage le plus de cas) au lieu d'un LIMIT 1 arbitraire.
 6. ✅ CLÔTURE AUTOMATIQUE (optionnelle) : les foyers sans cas récent passent à
       RESOLU + notification (activable via DBSCAN_CLOTURE_AUTO=true dans .env).
 7. 🐛 CORRIGÉ : en cas d'échec, l'erreur est REMONTÉE (raise) — l'API
       /api/admin/trigger-dbscan renvoie un vrai 500 au lieu d'un faux succès.
 8. 🐛 CORRIGÉ : l'ancien ON CONFLICT (id_cluster, id_cas_maladie) supposait une
       contrainte UNIQUE existante ; le nouvel INSERT ... WHERE NOT EXISTS
       fonctionne quel que soit le schéma, sans créer de doublons.

Usage : python3 dbscan.py   (ou importé par main.py pour le CRON / l'API)
"""
import os
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from psycopg2.extras import RealDictCursor
from sklearn.cluster import DBSCAN

# ✅ Pool de connexions du projet (voir db.py) — thread-safe
from db import get_conn, put_conn

warnings.filterwarnings("ignore", category=UserWarning)

# --- PARAMÈTRES IA ---
MALADIE_ID = 1                 # 1 = Choléra
DISTANCE_METRES = 450          # Epsilon : rayon de voisinage spatial (450 m)
MIN_CAS_POUR_ALERTE = 3        # MinPts : nombre de cas requis pour former un foyer
RAYON_TERRE_M = 6_371_008.8    # Rayon terrestre en MÈTRES (Haversine)
FENETRE_ANALYSE_JOURS = 30     # Fenêtre temporelle d'analyse (cas récents)

# ⚠️ À vérifier avec votre table `statut` (le dashboard compte id_statut=3
#    comme "clusters actifs"). 4 = RESOLU est l'ID utilisé par la clôture auto.
ID_STATUT_ACTIF = 3
ID_STATUT_RESOLU = 4

# Clôture automatique des foyers sans cas récent (activée via .env :
# DBSCAN_CLOTURE_AUTO=true)
CLOTURE_AUTO = os.getenv("DBSCAN_CLOTURE_AUTO", "false").lower() == "true"


# ==========================================
# OUTILS DE DISTANCE (HAVERSINE VECTORISÉ)
# ==========================================
def haversine_distance(lat1, lon1, lat2, lon2):
    """Distance haversine (mètres) entre deux points.
    Conservée pour compatibilité — le module utilise désormais les
    versions vectorisées ci-dessous (10 à 100× plus rapides)."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * RAYON_TERRE_M * np.arcsin(np.sqrt(a))


def matrice_distances_haversine(coords_deg):
    """Matrice n×n des distances (mètres) entre tous les points.
    100 % vectorisé : remplace n² appels à haversine_distance().
    O(n²) en mémoire — largement suffisant pour une fenêtre de 30 jours
    (< 5000 cas) ; au-delà, repassez sur metric='haversine' (ball_tree)."""
    lat = np.radians(coords_deg[:, 0])
    lon = np.radians(coords_deg[:, 1])
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = (np.sin(dlat / 2) ** 2
         + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2)
    return 2 * RAYON_TERRE_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def distances_depuis_point(lat0, lon0, coords_deg):
    """Distances (mètres) entre un point (centroïde) et chaque coordonnée.
    Utilisé pour estimer le rayon du foyer."""
    lat = np.radians(coords_deg[:, 0])
    lon = np.radians(coords_deg[:, 1])
    lat0, lon0 = map(np.radians, [lat0, lon0])
    dlat = lat - lat0
    dlon = lon - lon0
    a = np.sin(dlat / 2) ** 2 + np.cos(lat0) * np.cos(lat) * np.sin(dlon / 2) ** 2
    return 2 * RAYON_TERRE_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


# ==========================================
# EXÉCUTION DU MACHINE LEARNING (DBSCAN)
# ==========================================
def executer_dbscan():
    print(f"\n[{datetime.now()}] 🔬 Démarrage de l'analyse IA (DBSCAN)...")

    # ✅ 1 connexion du pool pour TOUTE l'analyse (lecture + écritures
    #    dans la même transaction → cohérence et un seul commit)
    conn = get_conn()
    try:
        # ---------- ÉTAPE A : EXTRACTION & FILTRAGE ----------
        # ✅ Filtre sargable (>= CURRENT_DATE - interval) → l'index
        #    idx_cas_date de sql/indexes.sql est exploité.
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT cas.id, adr.latitude, adr.longitude, adr.niveau_precision
                FROM cas_maladie cas
                JOIN adresse adr ON cas.id_adresse = adr.id
                WHERE cas.id_maladie = %s
                  AND cas.date_enregistrement >= CURRENT_DATE - %s
                  AND adr.niveau_precision != 'INCONNU';
            """, (MALADIE_ID, timedelta(days=FENETRE_ANALYSE_JOURS)))
            lignes = cur.fetchall()

        if not lignes:
            print("   -> Aucun cas géolocalisable avec précision trouvé.")
            return

        df = pd.DataFrame(lignes)
        print(f"   -> {len(df)} cas précis récupérés pour l'analyse spatiale.")

        # ---------- ÉTAPE B : ENTRAÎNEMENT DU MODÈLE ----------
        coords = df[["latitude", "longitude"]].to_numpy(dtype=float)
        matrice_m = matrice_distances_haversine(coords)  # distances en mètres

        db = DBSCAN(eps=DISTANCE_METRES, min_samples=MIN_CAS_POUR_ALERTE, metric="precomputed")
        df["cluster_label"] = db.fit_predict(matrice_m)

        clusters_trouves = df[df["cluster_label"] != -1]
        labels_uniques = clusters_trouves["cluster_label"].unique()
        print(f"   🚨 {len(labels_uniques)} foyer(s) épidémique(s) détecté(s).")
        nb_notifications = 0

        # ---------- ÉTAPE C : ÉCRITURES (même transaction) ----------
        with conn.cursor() as cur:
            for label in labels_uniques:
                groupe = clusters_trouves[clusters_trouves["cluster_label"] == label]
                ids = [int(x) for x in groupe["id"].tolist()]
                coords_groupe = groupe[["latitude", "longitude"]].to_numpy(dtype=float)

                centre_lat = float(groupe["latitude"].mean())
                centre_lon = float(groupe["longitude"].mean())
                nombre_cas = len(groupe)

                rayon_estime = int(distances_depuis_point(centre_lat, centre_lon, coords_groupe).max())
                if rayon_estime < 100:
                    rayon_estime = 100

                # --- Ce foyer existe-t-il déjà ? -------------------------------
                # ✅ Amélioration : on cherche le foyer DOMINANT partageant ces
                #    cas (fusion propre si DBSCAN regroupe deux anciens foyers),
                #    au lieu d'un LIMIT 1 arbitraire.
                cur.execute("""
                    SELECT cc.id_cluster
                    FROM cluster_cas cc
                    WHERE cc.id_cas_maladie = ANY(%s)
                    GROUP BY cc.id_cluster
                    ORDER BY COUNT(*) DESC
                    LIMIT 1;
                """, (ids,))
                resultat_existant = cur.fetchone()

                if resultat_existant:
                    id_cluster_db = resultat_existant[0]

                    # 🌟 ÉVITER LE SPAM : comparer avec l'ancien nombre de cas
                    cur.execute(
                        "SELECT nombre_cas_actuel FROM cluster_epidemique WHERE id = %s;",
                        (id_cluster_db,),
                    )
                    ancien_nombre = cur.fetchone()[0]

                    cur.execute("""
                        UPDATE cluster_epidemique
                        SET rayon_actuel = %s, nombre_cas_actuel = %s,
                            centre_latitude_actuel = %s, centre_longitude_actuel = %s
                        WHERE id = %s;
                    """, (rayon_estime, nombre_cas, centre_lat, centre_lon, id_cluster_db))

                    if nombre_cas > ancien_nombre:
                        nouveaux_cas = nombre_cas - ancien_nombre
                        cur.execute("""
                            INSERT INTO notification (titre, message, type_alerte, role_cible)
                            VALUES (%s, %s, 'AVERTISSEMENT', 'MCZ');
                        """, ("AGGRAVATION D'UN FOYER",
                              f"Le foyer #{id_cluster_db} a enregistré {nouveaux_cas} nouveau(x) cas. "
                              f"Il compte désormais {nombre_cas} cas actifs."))
                        nb_notifications += 1
                        print(f"      🔄 Foyer #{id_cluster_db} aggravé (+{nouveaux_cas} cas) -> Notification envoyée.")
                    else:
                        print(f"      🔄 Foyer #{id_cluster_db} mis à jour (aucun nouveau cas).")
                else:
                    # 🌟 NOUVEAU FOYER
                    cur.execute("""
                        INSERT INTO cluster_epidemique
                            (rayon_actuel, nombre_cas_actuel, centre_latitude_actuel,
                             centre_longitude_actuel, id_maladie, id_statut)
                        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
                    """, (rayon_estime, nombre_cas, centre_lat, centre_lon,
                          MALADIE_ID, ID_STATUT_ACTIF))
                    id_cluster_db = cur.fetchone()[0]

                    cur.execute("""
                        INSERT INTO notification (titre, message, type_alerte, role_cible)
                        VALUES (%s, %s, 'URGENCE', 'MCZ');
                    """, ("NOUVEAU FOYER DÉTECTÉ",
                          f"L'IA a identifié un nouveau cluster épidémique (Foyer #{id_cluster_db}) "
                          f"avec {nombre_cas} cas."))
                    nb_notifications += 1
                    print(f"      ⚠️ NOUVEAU FOYER #{id_cluster_db} détecté avec {nombre_cas} cas -> Notification envoyée.")

                # --- Rattachement des cas : 1 SEULE requête, sans doublons ---
                # ✅ remplace la boucle d'INSERT par cas (N+1) ET ne dépend
                #    d'aucune contrainte UNIQUE (ON CONFLICT inutile).
                cur.execute("""
                    INSERT INTO cluster_cas (id_cluster, id_cas_maladie)
                    SELECT %s, x
                    FROM unnest(%s) AS x
                    WHERE NOT EXISTS (
                        SELECT 1 FROM cluster_cas cc2
                        WHERE cc2.id_cluster = %s AND cc2.id_cas_maladie = x
                    );
                """, (id_cluster_db, ids, id_cluster_db))

            # ---------- ÉTAPE D : CLÔTURE AUTOMATIQUE (optionnelle) ----------
            # Foyers actifs sans aucun cas dans la fenêtre d'analyse → RESOLU.
            if CLOTURE_AUTO:
                cur.execute("""
                    UPDATE cluster_epidemique
                    SET id_statut = %s
                    WHERE id_statut = %s
                      AND id_maladie = %s
                      AND id NOT IN (
                          SELECT cc.id_cluster
                          FROM cluster_cas cc
                          JOIN cas_maladie cm ON cm.id = cc.id_cas_maladie
                          WHERE cm.date_enregistrement >= CURRENT_DATE - %s
                      )
                    RETURNING id;
                """, (ID_STATUT_RESOLU, ID_STATUT_ACTIF, MALADIE_ID,
                      timedelta(days=FENETRE_ANALYSE_JOURS)))
                foyers_fermes = [r[0] for r in cur.fetchall()]

                for foyer_id in foyers_fermes:
                    cur.execute("""
                        INSERT INTO notification (titre, message, type_alerte, role_cible)
                        VALUES (%s, %s, 'INFO', 'MCZ');
                    """, ("FOYER RÉSOLU",
                          f"Le foyer #{foyer_id} ne présente plus de cas récent : "
                          f"il a été clôturé automatiquement."))
                    nb_notifications += 1
                    print(f"      🟢 Foyer #{foyer_id} clôturé (plus de cas depuis {FENETRE_ANALYSE_JOURS} jours).")

        conn.commit()
        print(f"   ✅ Modélisation spatiale sauvegardée ({nb_notifications} notification(s)).\n")
        return {"clusters": int(len(labels_uniques)), "notifications": nb_notifications}

    except Exception as e:
        conn.rollback()
        print(f"   ❌ Erreur critique DBSCAN : {e}")
        raise  # 🐛 CORRIGÉ : l'API renverra un vrai 500 au lieu d'un faux succès
    finally:
        put_conn(conn)  # ✅ connexion RENDUE au pool — surtout pas conn.close()


if __name__ == "__main__":
    executer_dbscan()
