"""
main.py — API Backend SIMR (Système d'Information de Surveillance Épidémiologique)
=====================================================================================
OPTIMISATIONS APPLIQUÉES :
 1. ✅ Pool de connexions PostgreSQL (voir db.py) :
       fini les connexions TCP créées/détruites à chaque requête HTTP.
 2. ✅ Toutes les routes sont désormais SYNCHRONES (`def` au lieu de `async def`).
       FastAPI les exécute dans son threadpool → la boucle asyncio n'est JAMAIS
       bloquée par psycopg2 (driver synchrone). L'API reste réactive pour tous.
 3. ✅ Curseurs unifiés en RealDictCursor via db_cursor() :
       l'ancien code mélangeait curseurs tuple/dict selon les routes (fragile).
 4. ✅ Requêtes SQL optimisées : filtres sargables (index exploitables),
       NOT IN remplacé par LEFT JOIN ... IS NULL, aucun SELECT *, pas de N+1.
 5. ✅ Index de performance dans sql/indexes.sql + bulk_insert (db.py)
       pour les insertions en masse.

⚠️ ROUTES CONSERVÉES À L'IDENTIQUE (mêmes URLs, mêmes réponses JSON)
   pour ne rien casser côté front-end Angular.
"""

import os
import shutil
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import psycopg2
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db import close_pool, db_cursor, get_conn

# Modules d'Intelligence Artificielle du projet
import geocode
import ocr_simr


# ==========================================
# RÉTRO-COMPATIBILITÉ (anciens modules)
# ==========================================
def get_db_connection():
    """⚠️ Dépréciée — conservée si vos modules (dbscan.py, geocode.py, ...)
    font `from main import get_db_connection`.
    Mieux : dans ces modules, utilisez `from db import db_cursor`.
    ⚠️ Ne JAMAIS fermer la connexion retournée (`conn.close()`) :
    rendez-la avec `from db import put_conn`."""
    return get_conn()


# ==========================================
# CRON JOB (Tâches planifiées)
# ==========================================
def tache_planifiee_dbscan():
    """Exécutée par APScheduler dans un thread d'arrière-plan.
    Le pool ThreadedConnectionPool est thread-safe : dbscan.py peut donc
    utiliser `from db import db_cursor` sans danger."""
    print(f"[{datetime.now()}] CRON JOB : Lancement automatique de l'algorithme DBSCAN...")
    try:
        import dbscan
        dbscan.executer_dbscan()
        print("CRON JOB : Analyse DBSCAN terminée avec succès.")
    except Exception as e:
        print(f"CRON JOB : Erreur lors de l'exécution de DBSCAN - {str(e)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(tache_planifiee_dbscan, "interval", minutes=30, id="job_dbscan")
    scheduler.start()
    print("[SIMR] Planificateur démarré — DBSCAN toutes les 30 minutes.")
    yield
    scheduler.shutdown(wait=False)
    close_pool()
    print("[SIMR] Planificateur arrêté, pool de connexions fermé.")


# ==========================================
# INITIALISATION FASTAPI
# ==========================================
app = FastAPI(
    title="SIMR App - Backend API",
    description="API pour le Système d'Information de Surveillance Épidémiologique",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "https://front-end-simr.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Gestionnaire d'erreurs GLOBAL : remplace le try/except + traceback.print_exc()
# qui était dupliqué dans chaque route (1 seul endroit à maintenir).
@app.exception_handler(Exception)
async def gestionnaire_erreurs_global(request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ==========================================
# ROUTE : SANTÉ DU SYSTÈME (health check)
# ==========================================
@app.get("/api/health")
def health():
    """Vérifie que le pool et la base répondent (utile pour Render/Railway/UptimeRobot)."""
    with db_cursor() as cur:
        cur.execute("SELECT 1;")
    return {"status": "ok"}


# ==========================================
# ROUTES : TRIGGER DBSCAN
# ==========================================
@app.post("/api/admin/trigger-dbscan")
def trigger_dbscan_manually():
    import dbscan
    dbscan.executer_dbscan()
    return {"message": "Algorithme DBSCAN exécuté avec succès."}


@app.post("/api/admin/run-dbscan")
def trigger_dbscan():
    """⚠️ Doublon de /api/admin/trigger-dbscan, conservé pour compatibilité front-end."""
    tache_planifiee_dbscan()
    return {"message": "DBSCAN exécuté avec succès."}


# ==========================================
# ROUTES : AUTHENTIFICATION & STATUT SYSTÈME
# ==========================================
class LoginData(BaseModel):
    login: str
    mdp: str


@app.post("/api/auth/login")
def login(credentials: LoginData):
    with db_cursor() as cur:
        cur.execute("""
            SELECT u.id, u.nom_utilisateur, u.etat, r.nom AS nom_role,
                   u.id_centre_sante,
                   c.nom AS nom_centre,
                   z.id AS id_zone, z.nom AS nom_zone,
                   c.etat AS etat_centre, a.etat AS etat_aire
            FROM utilisateur u
            JOIN role_utilisateur r ON u.id_role = r.id
            LEFT JOIN centre_sante c ON u.id_centre_sante = c.id
            LEFT JOIN aire_sante a ON c.id_aire_sante = a.id
            LEFT JOIN (SELECT id, nom FROM zone_sante LIMIT 1) z ON TRUE
            WHERE u.nom_utilisateur = %s AND u.mot_de_passe = %s;
        """, (credentials.login, credentials.mdp))
        user_db = cur.fetchone()

    if not user_db:
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect.")

    if user_db["etat"] != "ACTIF":
        raise HTTPException(status_code=403, detail="Ce compte a été désactivé.")

    if (user_db["nom_role"] != "MCZ"
            and (user_db["etat_centre"] == "INACTIF" or user_db["etat_aire"] == "INACTIF")):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : Votre centre ou aire de santé a été fermé ou désactivé par l'administration.",
        )

    return {
        "token": f"token_{user_db['id']}_{user_db['nom_role']}",
        "utilisateur": {
            "id": user_db["id"],
            "login": user_db["nom_utilisateur"],
            "role": user_db["nom_role"],
            "id_centre_sante": user_db["id_centre_sante"],
            "nom_centre": user_db["nom_centre"] or "Aucun",
            "id_zone": user_db["id_zone"] or 0,
            "zone": user_db["nom_zone"] or "Zone non configurée",
        },
    }


@app.get("/api/system-status")
def get_system_status():
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count_val FROM zone_sante;")
            result = cur.fetchone()
        return {"isConfigured": bool(result["count_val"] > 0)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur DB : {str(e)}")


# ==========================================
# ROUTES : TABLEAU DE BORD & CARTOGRAPHIE
# ==========================================
@app.get("/api/dashboard/stats")
def get_dashboard_stats(role: str = "MCZ", id_centre: int = 0):
    with db_cursor() as cur:
        if role == "MCZ":
            # ✅ 1 SEULE requête (sous-requêtes agrégées) → pas de N+1
            cur.execute("""
                SELECT
                    (SELECT COUNT(id) FROM cas_maladie
                     WHERE date_enregistrement >= CURRENT_DATE - INTERVAL '7 days') AS nouveaux_cas,

                    (SELECT COUNT(id) FROM cluster_epidemique
                     WHERE id_statut = 3) AS clusters_actifs,

                    (SELECT COUNT(id) FROM cas_maladie
                     WHERE id_statut = 1) AS fiches_attente_validation;
            """)
            stats = cur.fetchone()
            return {
                "nouveauxCas": stats["nouveaux_cas"] or 0,
                "clustersActifs": stats["clusters_actifs"] or 0,
                "fichesAttente": stats["fiches_attente_validation"] or 0,
            }

        # Médecin / Infirmier : 1 seule requête aussi.
        # ✅ Optimisation : DATE(date_enregistrement) = CURRENT_DATE empêchait
        #    l'index d'être utilisé → remplacé par un intervalle sargable.
        cur.execute("""
            SELECT
                COUNT(c.id) FILTER (WHERE c.date_enregistrement >= CURRENT_DATE
                                    AND c.date_enregistrement < CURRENT_DATE + INTERVAL '1 day') AS cas_aujourdhui,

                COUNT(c.id) FILTER (WHERE c.date_enregistrement >= CURRENT_DATE - INTERVAL '7 days') AS cas_semaine,

                COALESCE(
                    ROUND(
                        (COUNT(c.id) FILTER (WHERE a.niveau_precision IN ('GPS_EXACT', 'ADRESSE')) * 100.0)
                        / NULLIF(COUNT(c.id), 0)
                    ), 0
                ) AS taux_precision
            FROM cas_maladie c
            LEFT JOIN adresse a ON c.id_adresse = a.id
            WHERE c.id_centre_sante = %s;
        """, (id_centre,))
        stats = cur.fetchone()
        return {
            "casSoumisAujourdhui": stats["cas_aujourdhui"] or 0,
            "casSoumisSemaine": stats["cas_semaine"] or 0,
            "tauxSaisieReussie": stats["taux_precision"],
        }


@app.get("/api/map/clusters")
def get_map_clusters():
    with db_cursor() as cur:
        # 1. Clusters (avec leur statut)
        cur.execute("""
            SELECT c.id, c.rayon_actuel AS rayon, c.nombre_cas_actuel AS cas,
                   c.centre_latitude_actuel AS lat, c.centre_longitude_actuel AS lng,
                   s.nom AS statut, 'Zone Inconnue' AS zone
            FROM cluster_epidemique c
            JOIN statut s ON c.id_statut = s.id;
        """)
        clusters = cur.fetchall()

        # 2. Cas isolés (bruit DBSCAN) : cas non rattachés à un cluster.
        # ✅ Optimisation : LEFT JOIN ... IS NULL remplace NOT IN (SELECT ...)
        #    → plus rapide avec l'index sur cluster_cas.id_cas_maladie,
        #    et immunisé contre les NULL de cette colonne.
        cur.execute("""
            SELECT cm.id, a.latitude AS lat, a.longitude AS lng
            FROM cas_maladie cm
            JOIN adresse a ON cm.id_adresse = a.id
            LEFT JOIN cluster_cas cc ON cc.id_cas_maladie = cm.id
            WHERE cc.id IS NULL
              AND a.niveau_precision != 'INCONNU'
              AND cm.date_enregistrement >= CURRENT_DATE - INTERVAL '30 days';
        """)
        bruit = cur.fetchall()

    return {"clusters": clusters, "bruit": bruit}


# ==========================================
# ROUTES : ADMINISTRATION PYRAMIDE
# ==========================================
class ZoneSanteCreate(BaseModel):
    nom: str
    code: str
    province: str
    population: Optional[int] = 0


@app.post("/api/admin/zones")
def creer_zone_sante(zone: ZoneSanteCreate):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO zone_sante (nom, code, province, population)
            VALUES (%s, %s, %s, %s) RETURNING id;
        """, (zone.nom, zone.code, zone.province, zone.population))
        new_id = cur.fetchone()["id"]
    return {"message": "Zone de santé créée", "id": new_id}


@app.put("/api/admin/zones/{zone_id}")
def modifier_zone_sante(zone_id: int, zone: ZoneSanteCreate):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE zone_sante
            SET nom = %s, code = %s, province = %s, population = %s
            WHERE id = %s;
        """, (zone.nom, zone.code, zone.province, zone.population, zone_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Zone de santé introuvable.")
    return {"message": "Zone de santé mise à jour !"}


@app.get("/api/admin/zones")
def get_zones_sante():
    with db_cursor() as cur:
        cur.execute("SELECT id, nom, code, province, population FROM zone_sante ORDER BY nom;")
        return cur.fetchall()


class AireSanteCreate(BaseModel):
    nom: str
    population: Optional[int] = 0
    id_zone_sante: int


@app.post("/api/admin/aires")
def creer_aire_sante(aire: AireSanteCreate):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO aire_sante (nom, population, id_zone_sante, etat)
            VALUES (%s, %s, %s, 'ACTIF') RETURNING id;
        """, (aire.nom, aire.population, aire.id_zone_sante))
        new_id = cur.fetchone()["id"]
    return {
        "message": "Aire de santé créée",
        "id": new_id,
        "nom": aire.nom,
        "population": aire.population,
    }


@app.put("/api/admin/aires/{aire_id}")
def modifier_aire_sante(aire_id: int, aire: AireSanteCreate):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE aire_sante
            SET nom = %s, population = %s
            WHERE id = %s AND etat = 'ACTIF';
        """, (aire.nom, aire.population, aire_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Aire introuvable ou inactive.")
    return {"message": "Aire de santé mise à jour !"}


@app.get("/api/admin/aires")
def get_aires_sante(zone_id: Optional[int] = None):
    with db_cursor() as cur:
        if zone_id:
            cur.execute("""
                SELECT id, nom, population
                FROM aire_sante
                WHERE id_zone_sante = %s AND etat = 'ACTIF'
                ORDER BY nom;
            """, (zone_id,))
        else:
            cur.execute("""
                SELECT id, nom, population
                FROM aire_sante
                WHERE etat = 'ACTIF'
                ORDER BY nom;
            """)
        return cur.fetchall()


@app.delete("/api/admin/aires/{aire_id}")
def supprimer_aire_sante(aire_id: int):
    # LOGIQUE MÉTIER : refus formel s'il reste des centres ACTIFS dans l'aire
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS nb FROM centre_sante WHERE id_aire_sante = %s AND etat = 'ACTIF';",
            (aire_id,),
        )
        nb_centres = cur.fetchone()["nb"]

    if nb_centres > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Impossible de supprimer : Cette aire contient encore {nb_centres} centre(s) "
                   f"de santé actif(s). Veuillez d'abord supprimer ou déplacer ces centres.",
        )

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM aire_sante WHERE id = %s;", (aire_id,))
        message = "Aire de santé supprimée définitivement."
    except psycopg2.errors.ForeignKeyViolation:
        # Historique médical lié → soft delete au lieu d'une suppression physique
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE aire_sante SET etat = 'INACTIF' WHERE id = %s;", (aire_id,))
        message = "L'aire a été désactivée (Conserve un historique médical caché)."

    return {"message": message}


class CentreSanteCreate(BaseModel):
    nom: str
    type_centre: str
    id_aire_sante: int


@app.post("/api/admin/centres")
def creer_centre_sante(centre: CentreSanteCreate):
    # 1. Vérifier que l'aire de santé existe
    with db_cursor() as cur:
        cur.execute("SELECT nom FROM aire_sante WHERE id = %s;", (centre.id_aire_sante,))
        aire_row = cur.fetchone()

    if not aire_row:
        raise HTTPException(
            status_code=400,
            detail=f"L'aire de santé avec l'ID {centre.id_aire_sante} n'existe pas.",
        )

    # 2. Création du centre (état ACTIF)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO centre_sante (nom, type_centre, id_aire_sante, etat)
                VALUES (%s, %s, %s, 'ACTIF') RETURNING id;
            """, (centre.nom, centre.type_centre, centre.id_aire_sante))
            new_id = cur.fetchone()["id"]
    except psycopg2.errors.ForeignKeyViolation:
        raise HTTPException(status_code=400, detail="L'aire de santé spécifiée est invalide.")

    return {
        "message": "Centre de santé créé",
        "id": new_id,
        "nom": centre.nom,
        "type_centre": centre.type_centre,
        "id_aire_sante": centre.id_aire_sante,
        "aire_nom": aire_row["nom"],
    }


@app.get("/api/admin/centres")
def get_centres_sante(zone_id: Optional[int] = None):
    with db_cursor() as cur:
        if zone_id:
            cur.execute("""
                SELECT c.id, c.nom, c.type_centre, c.id_aire_sante, a.nom AS aire_nom
                FROM centre_sante c
                JOIN aire_sante a ON c.id_aire_sante = a.id
                WHERE a.id_zone_sante = %s AND c.etat = 'ACTIF'
                ORDER BY c.nom;
            """, (zone_id,))
        else:
            cur.execute("""
                SELECT c.id, c.nom, c.type_centre, c.id_aire_sante, a.nom AS aire_nom
                FROM centre_sante c
                JOIN aire_sante a ON c.id_aire_sante = a.id
                WHERE c.etat = 'ACTIF'
                ORDER BY c.nom;
            """)
        return cur.fetchall()


@app.put("/api/admin/centres/{centre_id}")
def modifier_centre_sante(centre_id: int, centre: CentreSanteCreate):
    # 1. Vérifier que la nouvelle aire existe
    with db_cursor() as cur:
        cur.execute("SELECT nom FROM aire_sante WHERE id = %s;", (centre.id_aire_sante,))
        aire_row = cur.fetchone()

    if not aire_row:
        raise HTTPException(
            status_code=400,
            detail=f"L'aire de santé avec l'ID {centre.id_aire_sante} n'existe pas.",
        )

    # 2. Mise à jour du centre (s'il est actif)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE centre_sante
                SET nom = %s, type_centre = %s, id_aire_sante = %s
                WHERE id = %s AND etat = 'ACTIF';
            """, (centre.nom, centre.type_centre, centre.id_aire_sante, centre_id))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Centre introuvable ou inactif.")
    except psycopg2.errors.ForeignKeyViolation:
        raise HTTPException(status_code=400, detail="L'aire de santé spécifiée est invalide.")

    return {
        "message": "Centre de santé mis à jour",
        "id": centre_id,
        "nom": centre.nom,
        "type_centre": centre.type_centre,
        "id_aire_sante": centre.id_aire_sante,
        "aire_nom": aire_row["nom"],
    }


@app.delete("/api/admin/centres/{centre_id}")
def supprimer_centre_sante(centre_id: int):
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS nb FROM cas_maladie WHERE id_centre_sante = %s;", (centre_id,))
        nb_cas = cur.fetchone()["nb"]

    if nb_cas > 0:
        # Le centre possède un historique → soft delete
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE centre_sante SET etat = 'INACTIF' WHERE id = %s;", (centre_id,))
        return {"message": f"Le centre a été désactivé (INACTIF) car il contient {nb_cas} cas d'épidémie."}

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM centre_sante WHERE id = %s AND etat = 'ACTIF';", (centre_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Centre introuvable ou déjà inactif.")
        return {"message": "Centre de santé supprimé définitivement."}
    except psycopg2.errors.ForeignKeyViolation:
        # Des médecins/utilisateurs y sont affectés → soft delete
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE centre_sante SET etat = 'INACTIF' WHERE id = %s;", (centre_id,))
        return {"message": "Le centre a été désactivé (Des médecins/utilisateurs y sont affectés)."}


# ==========================================
# ROUTES : UTILISATEURS (COMPTES)
# ==========================================
class UtilisateurCreate(BaseModel):
    id: Optional[int] = None
    nom: Optional[str] = None       # Optionnel (rétro-compatibilité front-end)
    login: str
    mdp: str
    role: str
    id_centre: Optional[int] = None  # Accepte None/null pour le MCZ
    sexe: str = "M"
    telephone: str = ""


@app.post("/api/admin/utilisateurs")
def creer_utilisateur(user: UtilisateurCreate):
    if user.role == "MCZ":
        id_role = 1
        user.id_centre = None  # Le MCZ n'a pas de centre
    elif user.role == "MEDECIN":
        id_role = 2
    else:
        id_role = 3

    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO utilisateur (nom_utilisateur, mot_de_passe, etat, id_role, sexe, telephone, id_centre_sante)
            VALUES (%s, %s, 'ACTIF', %s, %s, %s, %s) RETURNING id;
        """, (user.login, user.mdp, id_role, user.sexe, user.telephone, user.id_centre))
        new_id = cur.fetchone()["id"]

    return {"message": "Utilisateur créé", "id": new_id}


@app.put("/api/admin/utilisateurs/{user_id}")
def modifier_utilisateur(user_id: int, user: UtilisateurCreate):
    if user.role == "MCZ":
        id_role = 1
        user.id_centre = None
    elif user.role == "MEDECIN":
        id_role = 2
    else:
        id_role = 3

    with db_cursor(commit=True) as cur:
        if user.mdp and user.mdp.strip() != "":
            cur.execute("""
                UPDATE utilisateur
                SET nom_utilisateur = %s, mot_de_passe = %s, id_role = %s,
                    sexe = %s, telephone = %s, id_centre_sante = %s
                WHERE id = %s;
            """, (user.login, user.mdp, id_role, user.sexe, user.telephone, user.id_centre, user_id))
        else:
            cur.execute("""
                UPDATE utilisateur
                SET nom_utilisateur = %s, id_role = %s, sexe = %s, telephone = %s, id_centre_sante = %s
                WHERE id = %s;
            """, (user.login, id_role, user.sexe, user.telephone, user.id_centre, user_id))

    return {"message": "Utilisateur mis à jour !"}


@app.get("/api/admin/utilisateurs")
def get_utilisateurs():
    with db_cursor() as cur:
        cur.execute("""
            SELECT u.id, u.nom_utilisateur AS login, r.nom AS role,
                   COALESCE(c.nom, 'Zone Globale') AS centre,
                   u.sexe, u.telephone
            FROM utilisateur u
            JOIN role_utilisateur r ON u.id_role = r.id
            LEFT JOIN centre_sante c ON u.id_centre_sante = c.id
            WHERE r.nom IN ('MCZ', 'MEDECIN', 'INFIRMIER') AND u.etat = 'ACTIF'
            ORDER BY u.id DESC;
        """)
        return cur.fetchall()


@app.delete("/api/admin/utilisateurs/{user_id}")
def supprimer_utilisateur(user_id: int):
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS nb FROM cas_maladie WHERE id_utilisateur = %s;", (user_id,))
        nb_cas = cur.fetchone()["nb"]

    with db_cursor(commit=True) as cur:
        if nb_cas > 0:
            cur.execute("UPDATE utilisateur SET etat = 'INACTIF' WHERE id = %s;", (user_id,))
            message = (f"Ce compte a enregistré {nb_cas} cas. "
                       f"Il a été désactivé (INACTIF) au lieu d'être supprimé.")
        else:
            cur.execute("DELETE FROM utilisateur WHERE id = %s;", (user_id,))
            message = "Compte médical supprimé avec succès."

    return {"message": message}


# ==========================================
# ROUTES : SAISIE DES CAS (MANUELLE & OCR)
# ==========================================
class CasMaladieCreate(BaseModel):
    patientNom: str
    patientPrenom: str
    patientPostnom: Optional[str] = ""
    dateNaissance: Optional[str] = None
    sexe: str = "M"
    telephone: Optional[str] = ""
    commune: str
    quartier: str = ""
    avenue: str = ""
    numeroResidence: str = ""
    symptomes: str = ""
    statutId: int = 1
    sourceSaisie: str
    lat_gps: Optional[float] = None
    lng_gps: Optional[float] = None
    id_centre: int
    id_utilisateur: int


@app.post("/api/cas")
def creer_nouveau_cas(cas_data: CasMaladieCreate):
    # ✅ GÉOCODAGE AVANT de prendre une connexion :
    #    on ne monopolise pas une connexion du pool pendant un appel réseau long.
    coords = geocode.obtenir_coordonnees(
        avenue=cas_data.avenue,
        quartier=cas_data.quartier,
        commune=cas_data.commune,
        lat_gps=cas_data.lat_gps,
        lng_gps=cas_data.lng_gps,
    )

    with db_cursor(commit=True) as cur:
        # Insertion transactionnelle : tout est validé ensemble (commit auto
        # à la sortie du bloc) ou rien n'est enregistré (rollback auto).
        cur.execute("""
            INSERT INTO adresse (commune, quartier, avenue, numero, latitude, longitude, niveau_precision)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;
        """, (
            cas_data.commune,
            cas_data.quartier,
            cas_data.avenue,
            cas_data.numeroResidence,
            coords["lat"],
            coords["lng"],
            coords["precision"],
        ))
        id_adresse = cur.fetchone()["id"]  # ✅ RealDictCursor garanti par db_cursor

        cur.execute("""
            INSERT INTO patient (nom, prenom, post_nom, sexe, telephone, date_insertion, id_adresse)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s) RETURNING id;
        """, (cas_data.patientNom, cas_data.patientPrenom, cas_data.patientPostnom,
              cas_data.sexe, cas_data.telephone, id_adresse))
        id_patient = cur.fetchone()["id"]

        cur.execute("""
            INSERT INTO cas_maladie (id_patient, id_maladie, id_centre_sante, id_adresse, id_utilisateur, id_statut)
            VALUES (%s, 1, %s, %s, %s, %s) RETURNING id;
        """, (id_patient, cas_data.id_centre, id_adresse, cas_data.id_utilisateur, cas_data.statutId))
        id_cas = cur.fetchone()["id"]

        if cas_data.symptomes:
            cur.execute("""
                INSERT INTO symptome_cas (nom_symptome, id_cas_maladie)
                VALUES (%s, %s);
            """, (cas_data.symptomes, id_cas))

    return {
        "message": "Cas enregistré avec succès !",
        "cas_id": id_cas,
        "geo_precision": coords["precision"],
    }


# ==========================================
# ROUTES : NUMÉRISATION SIMR (OCR)
# ==========================================
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.post("/api/simr/upload")
def upload_simr_form(file: UploadFile = File(...)):
    # ✅ os.path.basename() → protection contre le path traversal (../../etc/passwd)
    filename = os.path.basename(file.filename or "fiche_simr")
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    result = ocr_simr.traiter_image_simr(file_path)
    return {"message": "Fiche scannée", "image_url": file_path, "ocr_data": result}


# ==========================================
# ROUTES : NOTIFICATIONS (CLOCHE)
# ==========================================
@app.get("/api/notifications")
def get_notifications(role: str = "MCZ"):
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, titre, message, type_alerte, est_lue, date_creation
            FROM notification
            WHERE role_cible = %s OR role_cible = 'TOUS'
            ORDER BY date_creation DESC
            LIMIT 15;
        """, (role,))
        return cur.fetchall()


@app.put("/api/notifications/{notif_id}/lire")
def marquer_notif_lue(notif_id: int):
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE notification SET est_lue = TRUE WHERE id = %s;", (notif_id,))
    return {"message": "Notification lue"}
