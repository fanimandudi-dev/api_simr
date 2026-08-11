import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import random
import math
from datetime import datetime, timedelta

# 1. Charger les variables d'environnement (Supabase/Local)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# --- SCÉNARIO PARFAIT POUR LE JURY ---
FOYERS = [
    # 1. FOYER DENSE (Le gros Cluster Rouge) : 80 patients collés dans un rayon de 500m à Mombele
    {"lat": -4.3415, "lng": 15.3210, "rayon_m": 500, "nb_cas": 80, "commune": "Limete", "quartier": "Mombele", "precision": "GPS_EXACT"},
    
    # 2. FOYER ÉMERGENT (Le Cluster Orange) : 20 patients dans 800m à Kingabwa
    {"lat": -4.3250, "lng": 15.3340, "rayon_m": 800, "nb_cas": 20, "commune": "Limete", "quartier": "Kingabwa", "precision": "OSM_ADRESSE"},
    
    # 3. LE BRUIT (Les points Bleus) : 10 patients répartis sur 15 kilomètres !
    {"lat": -4.3224, "lng": 15.3070, "rayon_m": 15000, "nb_cas": 10, "commune": "Gombe", "quartier": "Divers", "precision": "OSM_QUARTIER"}
]

def generer_point_aleatoire(lat_centre, lng_centre, rayon_m):
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
    print(f"[{datetime.now()}] Génération d'une simulation épidémiologique parfaite...")
    conn = None; cursor = None
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cursor = conn.cursor()

        # Nettoyage
        print("-> Suppression des anciennes données...")
        cursor.execute("DELETE FROM symptome_cas;")
        cursor.execute("DELETE FROM cluster_cas;")
        cursor.execute("DELETE FROM cluster_epidemique;")
        cursor.execute("DELETE FROM cas_maladie;")
        cursor.execute("DELETE FROM patient;")
        cursor.execute("DELETE FROM adresse;")
        
        # Séquences
        for table in ['adresse', 'patient', 'cas_maladie', 'cluster_epidemique']:
            try: cursor.execute(f"SELECT setval('{table}_id_seq', 1, false);")
            except: pass

        # Récupération Centre et User
        cursor.execute("SELECT id FROM centre_sante LIMIT 1;")
        c = cursor.fetchone()
        if not c: return print("❌ ERREUR: Aucun Centre de Santé trouvé.")
        id_centre = c['id']

        cursor.execute("SELECT id FROM utilisateur LIMIT 1;")
        u = cursor.fetchone()
        id_user = u['id'] if u else 1

        cas_crees = 0
        date_actuelle = datetime.now()

        for foyer in FOYERS:
            for i in range(foyer["nb_cas"]):
                lat, lng = generer_point_aleatoire(foyer["lat"], foyer["lng"], foyer["rayon_m"])
                jours = random.randint(0, 10)
                date_enreg = date_actuelle - timedelta(days=jours)
                
                # Adresse
                cursor.execute("""
                    INSERT INTO adresse (commune, quartier, latitude, longitude, niveau_precision)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id;
                """, (foyer["commune"], foyer["quartier"], lat, lng, foyer["precision"]))
                id_adresse = cursor.fetchone()['id']

                # Patient
                cursor.execute("""
                    INSERT INTO patient (nom, prenom, sexe, id_adresse)
                    VALUES (%s, 'Anonyme', 'M', %s) RETURNING id;
                """, (f"Patient_{cas_crees}", id_adresse))
                id_patient = cursor.fetchone()['id']

                # Cas
                cursor.execute("""
                    INSERT INTO cas_maladie (date_enregistrement, id_patient, id_maladie, id_centre_sante, id_adresse, id_utilisateur, id_statut)
                    VALUES (%s, %s, 1, %s, %s, %s, 1) RETURNING id;
                """, (date_enreg, id_patient, id_centre, id_adresse, id_user))
                cas_crees += 1

        conn.commit()
        print(f"✅ SUCCÈS : {cas_crees} cas ont été générés. Lancez maintenant l'IA !")

    except Exception as e:
        print(f"❌ Erreur : {e}")
        if conn: conn.rollback()
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

if __name__ == "__main__":
    generer_epidemiologie()