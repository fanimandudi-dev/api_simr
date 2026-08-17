import os
import psycopg2
from dotenv import load_dotenv
from faker import Faker
import random
import math
from datetime import datetime, timedelta

# =================================================================
# CONFIGURATION DES FOYERS ET DU BRUIT SPATIAL
# =================================================================
FOYERS = [
    # 1. FOYER DENSE (Le Gros Cluster Rouge)
    # Centré sur Limete/Mombele avec un rayon très serré de 300m
    {"lat": -4.3415, "lng": 15.3210, "rayon_m": 300, "nb_cas": 65, "commune": "Limete", "quartier": "Mombele", "precision": "GPS_EXACT"},
    
    # 2. FOYER ÉMERGENT (Le Cluster Orange)
    # Centré sur Kingabwa avec un rayon de 450m
    {"lat": -4.3250, "lng": 15.3340, "rayon_m": 450, "nb_cas": 40, "commune": "Limete", "quartier": "Kingabwa", "precision": "OSM_ADRESSE"},
    
    # 3. LE BRUIT (Les points bleus dispersés sur Kinshasa)
    # Centré sur Kalamu et dispersé sur un rayon de 3500m (3.5 km)
    {"lat": -4.3500, "lng": 15.3100, "rayon_m": 3500, "nb_cas": 195, "commune": "Kalamu", "quartier": "Divers", "precision": "OSM_QUARTIER"}
]

def generer_point_jitter(lat_centre: float, lng_centre: float, rayon_m: float):
    """
    Génère un point aléatoire uniformément distribué à l'intérieur
    d'un cercle de rayon rayon_m autour d'un centre (lat, lng).
    """
    R_terre = 6371000.0  # Rayon de la Terre en mètres
    
    # Distribution uniforme sur la surface du disque
    r = rayon_m * math.sqrt(random.random())
    theta = random.uniform(0, 2 * math.pi)
    
    # Déplacement en mètres
    dx = r * math.cos(theta)
    dy = r * math.sin(theta)
    
    # Conversion en dLat et dLng en degrés
    dlat = (dy / R_terre) * (180 / math.pi)
    dlng = (dx / (R_terre * math.cos(math.radians(lat_centre)))) * (180 / math.pi)
    
    return lat_centre + dlat, lng_centre + dlng

def seed_profond():
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ ERREUR: DATABASE_URL introuvable.")
        return

    fake = Faker('fr_FR')
    print("🌍 Démarrage du Seeding Profond (Mass Data Generation basé sur FOYERS)...")
    conn = None
    cursor = None

    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()

        # =================================================================
        # 1. PYRAMIDE SANITAIRE
        # =================================================================
        print("   -> Génération de la Zone et des Aires de Santé...")
        cursor.execute("INSERT INTO zone_sante (nom, code, population, province) VALUES (%s, %s, %s, %s) RETURNING id;", 
                       ("Zone de Limete", "Z-LIM", 350000, "Kinshasa"))
        id_zone = cursor.fetchone()[0]

        aires_data = [
            ("Aire Mombele", 45000, -4.3415, 15.3210, id_zone),
            ("Aire Kingabwa", 65000, -4.3250, 15.3340, id_zone),
            ("Aire Ndjili", 40000, -4.3300, 15.3400, id_zone)
        ]
        cursor.executemany("INSERT INTO aire_sante (nom, population, latitude, longitude, id_zone_sante) VALUES (%s, %s, %s, %s, %s);", aires_data)
        
        print("   -> Génération des Centres de Santé...")
        cursor.execute("SELECT id FROM aire_sante ORDER BY id;")
        aires_ids = [row[0] for row in cursor.fetchall()]
        
        centres_data = []
        for i in range(10): # 10 Centres
            centres_data.append((
                f"Centre {fake.company()}", fake.city(), fake.street_name(), str(random.randint(1, 100)),
                "Centre de Référence", -4.33 + random.uniform(-0.02, 0.02), 15.32 + random.uniform(-0.02, 0.02),
                fake.name(), random.choice(aires_ids)
            ))
        cursor.executemany("""
            INSERT INTO centre_sante (nom, commune, avenue, numero, type_centre, latitude, longitude, responsable, id_aire_sante)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        """, centres_data)

        # =================================================================
        # 2. PERSONNEL SOIGNANT (Utilisateurs)
        # =================================================================
        print("   -> Génération du personnel soignant...")
        cursor.execute("SELECT id FROM role_utilisateur WHERE nom IN ('MEDECIN', 'INFIRMIER');")
        roles_ids = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("SELECT id FROM centre_sante;")
        centres_ids = [row[0] for row in cursor.fetchall()]
        
        users_data = []
        for i in range(20):
            users_data.append((
                f"user_{i}", "password123", random.choice(['M', 'F']), fake.phone_number(), 
                random.choice(roles_ids), random.choice(centres_ids)
            ))
        cursor.executemany("""
            INSERT INTO utilisateur (nom_utilisateur, mot_de_passe, sexe, telephone, id_role, id_centre_sante) 
            VALUES (%s, %s, %s, %s, %s, %s);
        """, users_data)

        # =================================================================
        # 3. DONNÉES CLINIQUES (Génération géospatiale basée sur FOYERS)
        # =================================================================
        print("   -> Génération des adresses structurées selon la topologie FOYERS...")
        adresses_data = []
        
        cursor.execute("SELECT COALESCE(MAX(id), 0) FROM adresse;")
        start_adresse_id = cursor.fetchone()[0] + 1
        
        # Génération des points d'adresses en suivant la répartition des foyers
        for foyer in FOYERS:
            for _ in range(foyer["nb_cas"]):
                lat_p, lng_p = generer_point_jitter(foyer["lat"], foyer["lng"], foyer["rayon_m"])
                
                quartier_nom = foyer["quartier"] if foyer["quartier"] != "Divers" else fake.street_name()
                
                adresses_data.append((
                    foyer["commune"], 
                    quartier_nom, 
                    fake.street_name(), 
                    str(random.randint(1, 120)),
                    lat_p, 
                    lng_p, 
                    foyer["precision"]
                ))
                
        nb_total_cas = len(adresses_data)
        
        cursor.executemany("""
            INSERT INTO adresse (commune, quartier, avenue, numero, latitude, longitude, niveau_precision)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
        """, adresses_data)

        print(f"   -> Génération de {nb_total_cas} patients et cas associés...")
        patients_data = []
        for i in range(nb_total_cas):
            patients_data.append((
                fake.last_name(), fake.first_name(), fake.last_name(), random.choice(['M', 'F']), 
                fake.phone_number(), start_adresse_id + i
            ))
        cursor.executemany("""
            INSERT INTO patient (nom, prenom, post_nom, sexe, telephone, id_adresse)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, patients_data)

        # Récupération des IDs pour le rattachement
        cursor.execute("SELECT id FROM utilisateur WHERE id_role IN (2, 3);")
        users_ids = [row[0] for row in cursor.fetchall()]
        cursor.execute("SELECT id FROM statut WHERE code IN ('CAS_SUSPECT', 'CAS_CONFIRME');")
        statut_ids = [row[0] for row in cursor.fetchall()]

        cas_data = []
        symptomes_data = []
        date_actuelle = datetime.now()

        cursor.execute("SELECT COALESCE(MAX(id), 0) FROM cas_maladie;")
        start_cas_id = cursor.fetchone()[0] + 1

        for i in range(nb_total_cas):
            # Simulation d'un historique sur les 30 derniers jours
            date_enreg = date_actuelle - timedelta(days=random.randint(0, 30))
            id_patient_attribue = start_adresse_id + i
            id_centre_attribue = random.choice(centres_ids)
            id_user_attribue = random.choice(users_ids)
            
            cas_data.append((
                date_enreg, id_patient_attribue, 1, id_centre_attribue, 
                id_patient_attribue, id_user_attribue, random.choice(statut_ids)
            ))
            
            # 1 à 3 symptômes par cas
            id_cas = start_cas_id + i
            for _ in range(random.randint(1, 3)):
                symptomes_data.append((random.choice(['Diarrhée', 'Vomissements', 'Déshydratation']), id_cas))

        cursor.executemany("""
            INSERT INTO cas_maladie (date_enregistrement, id_patient, id_maladie, id_centre_sante, id_adresse, id_utilisateur, id_statut)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
        """, cas_data)
        
        cursor.executemany("""
            INSERT INTO symptome_cas (nom_symptome, id_cas_maladie)
            VALUES (%s, %s);
        """, symptomes_data)

        conn.commit()
        print(f"✅ SUCCÈS : {nb_total_cas} cas insérés selon la topologie exacte des foyers DBSCAN.")

    except psycopg2.Error as e:
        if conn: conn.rollback()
        print(f"❌ ERREUR SQL : {e}")
    except Exception as e:
        if conn: conn.rollback()
        print(f"❌ ERREUR GLOBALE : {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

if __name__ == "__main__":
    seed_profond()