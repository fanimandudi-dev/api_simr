import os
import psycopg2
from dotenv import load_dotenv
from faker import Faker
import random
from datetime import datetime, timedelta

def seed_profond():
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ ERREUR: DATABASE_URL introuvable.")
        return

    fake = Faker('fr_FR')
    print("🌍 Démarrage du Seeding Profond (Mass Data Generation)...")
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
        # 3. DONNÉES CLINIQUES (Génération de 300 cas)
        # =================================================================
        print("   -> Génération de 300 cas médicaux (Adresses, Patients, Cas, Symptômes)...")
        NB_CAS = 300
        adresses_data = []
        
        # Astuce d'ingénierie : Optimisation des batchs avec executemany sur ID auto-incrémentés
        # Comme on a réinitialisé la DB, l'ID de la prochaine adresse sera le Max(ID)+1
        cursor.execute("SELECT COALESCE(MAX(id), 0) FROM adresse;")
        start_adresse_id = cursor.fetchone()[0] + 1
        
        precisions = ["GPS_EXACT", "OSM_ADRESSE", "OSM_QUARTIER"]
        for _ in range(NB_CAS):
            adresses_data.append((
                "Limete", fake.street_name(), fake.street_name(), str(random.randint(1, 100)),
                -4.33 + random.uniform(-0.03, 0.03), 15.32 + random.uniform(-0.03, 0.03), random.choice(precisions)
            ))
        cursor.executemany("""
            INSERT INTO adresse (commune, quartier, avenue, numero, latitude, longitude, niveau_precision)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
        """, adresses_data)

        patients_data = []
        for i in range(NB_CAS):
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

        for i in range(NB_CAS):
            # Simulation d'un historique sur les 30 derniers jours
            date_enreg = date_actuelle - timedelta(days=random.randint(0, 30))
            id_patient_attribue = start_adresse_id + i # Adresse ID == Patient ID car insertion 1:1
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
        print("✅ SUCCÈS : 300 cas générés et insérés avec leurs relations via Executemany.")

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