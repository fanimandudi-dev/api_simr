import math
import os
import random
from datetime import datetime, timedelta
import dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

# 1. Charger les variables d'environnement
dotenv.load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

FOYERS = [
    # Forcez 65 cas à s'entasser dans un minuscule cercle de 50 mètres ! 
    # DBSCAN sera obligé d'y voir un cluster très dense.
    {"lat": -4.3415, "lng": 15.3210, "rayon_m": 50, "nb_cas": 65, "commune": "Limete", "quartier": "Mombele", "precision": "GPS_EXACT"},
    
    # 40 cas entassés dans 100 mètres
    {"lat": -4.3250, "lng": 15.3340, "rayon_m": 100, "nb_cas": 40, "commune": "Limete", "quartier": "Kingabwa", "precision": "OSM_ADRESSE"},
    
    # Bruit : 15 cas répartis sur 5000 mètres (Eux resteront bleus et isolés)
    {"lat": -4.3224, "lng": 15.3070, "rayon_m": 5000, "nb_cas": 15, "commune": "Gombe", "quartier": "Divers", "precision": "OSM_QUARTIER"}
]


def generer_point_aleatoire(lat_centre, lng_centre, rayon_m):
    """Génère un point aléatoire dans un cercle d'un rayon donné (en mètres)."""
    rayon_degres = rayon_m / 111320.0
    u = random.random()
    v = random.random()
    w = rayon_degres * math.sqrt(u)
    t = 2 * math.pi * v
    x = w * math.cos(t)
    y = w * math.sin(t)

    new_lng = lng_centre + (x / math.cos(math.radians(lat_centre)))
    new_lat = lat_centre + y
    return new_lat, new_lng


def generer_epidemiologie():
    print(f"[{datetime.now()}] Démarrage de la génération de l'épidémie...")

    conn = None
    cursor = None

    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cursor = conn.cursor()

        # Configurer le schéma par défaut sur 'public'
        cursor.execute("SET search_path TO public;")

        # On nettoie d'abord les anciennes données cliniques
        print("-> Nettoyage de l'historique clinique existant...")
        cursor.execute("DELETE FROM public.symptome_cas;")
        cursor.execute("DELETE FROM public.cluster_cas;")
        cursor.execute("DELETE FROM public.cluster_epidemique;")
        cursor.execute("DELETE FROM public.cas_maladie;")
        cursor.execute("DELETE FROM public.patient;")
        cursor.execute("DELETE FROM public.adresse;")

        # Réinitialisation dynamique des séquences
        sequences = ["adresse", "patient", "cas_maladie", "cluster_epidemique"]
        for seq in sequences:
            try:
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('public.{seq}', 'id'), 1, false);"
                )
            except Exception:
                pass

        # Vérifier s'il y a un Centre de Santé disponible
        cursor.execute("SELECT id FROM public.centre_sante LIMIT 1;")
        centre_row = cursor.fetchone()
        if centre_row:
            id_centre_affectation = centre_row["id"]
        else:
            print("❌ ERREUR: Aucun Centre de Santé n'existe dans la table centre_sante.")
            return

        # Vérifier s'il y a un utilisateur
        cursor.execute(
            "SELECT id FROM public.utilisateur WHERE id_role IN (2, 3) LIMIT 1;"
        )
        user_row = cursor.fetchone()
        id_utilisateur = user_row["id"] if user_row else 1

        print("-> Génération des patients et des cas de choléra...")

        date_actuelle = datetime.now()
        cas_crees = 0

        for foyer in FOYERS:
            print(
                f"   - Génération de {foyer['nb_cas']} cas à {foyer['quartier']}..."
            )

            for i in range(foyer["nb_cas"]):
                # Coordonnées géographiques
                lat, lng = generer_point_aleatoire(
                    foyer["lat"], foyer["lng"], foyer["rayon_m"]
                )

                # Date d'enregistrement
                jours_en_arriere = random.choices(
                    [0, 1, 2, 3, 4, 5, 6, 7],
                    weights=[30, 20, 15, 10, 10, 5, 5, 5],
                )[0]
                date_enreg = date_actuelle - timedelta(days=jours_en_arriere)

                # Insertion Adresse
                cursor.execute(
                    """
                    INSERT INTO public.adresse (commune, quartier, latitude, longitude, niveau_precision)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id;
                """,
                    (
                        foyer["commune"],
                        foyer["quartier"],
                        lat,
                        lng,
                        foyer["precision"],
                    ),
                )
                id_adresse = cursor.fetchone()["id"]

                # Insertion Patient
                sexe = random.choice(["M", "F"])
                cursor.execute(
                    """
                    INSERT INTO public.patient (nom, prenom, sexe, id_adresse)
                    VALUES (%s, 'Anonyme', %s, %s) RETURNING id;
                """,
                    (f"Patient_{cas_crees + 1}", sexe, id_adresse),
                )
                id_patient = cursor.fetchone()["id"]

                # Insertion Cas
                statut = random.choice([1, 2])
                cursor.execute(
                    """
                    INSERT INTO public.cas_maladie (date_enregistrement, id_patient, id_maladie, id_centre_sante, id_adresse, id_utilisateur, id_statut)
                    VALUES (%s, %s, 1, %s, %s, %s, %s) RETURNING id;
                """,
                    (
                        date_enreg,
                        id_patient,
                        id_centre_affectation,
                        id_adresse,
                        id_utilisateur,
                        statut,
                    ),
                )

                cas_crees += 1

        conn.commit()
        print(
            f"\n✅ TERMINÉ : {cas_crees} cas ont été insérés dans la base de données Supabase avec succès !"
        )

    except Exception as e:
        print(f"\n❌ Erreur lors de l'insertion : {str(e)}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    generer_epidemiologie()