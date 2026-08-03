
import random
from datetime import datetime, timedelta
import math


import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# 1. Charger les variables d'environnement
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


# Coordonnées des foyers d'infection
FOYERS = [
    # 1. Le Cluster Massif de Limete / Mombele (Source d'eau contaminée)
    {"lat": -4.3415, "lng": 15.3210, "rayon_m": 300, "nb_cas": 65, "commune": "Limete", "quartier": "Mombele", "precision": "GPS_EXACT"},
    
    # 2. Le Cluster de Kingabwa (Plus diffus)
    {"lat": -4.3250, "lng": 15.3340, "rayon_m": 450, "nb_cas": 40, "commune": "Limete", "quartier": "Kingabwa", "precision": "OSM_ADRESSE"},
    
    # 3. Le "Bruit" (Noise) éparpillé dans tout Kinshasa
    {"lat": -4.3224, "lng": 15.3070, "rayon_m": 8000, "nb_cas": 15, "commune": "Gombe", "quartier": "Divers", "precision": "OSM_QUARTIER"}
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
    
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cursor = conn.cursor()

        # On nettoie d'abord les anciennes données cliniques
        print("-> Nettoyage de l'historique clinique existant...")
        cursor.execute("DELETE FROM symptome_cas;")
        cursor.execute("DELETE FROM cluster_cas;")
        cursor.execute("DELETE FROM cluster_epidemique;")
        cursor.execute("DELETE FROM cas_maladie;")
        cursor.execute("DELETE FROM patient;")
        cursor.execute("DELETE FROM adresse;")
        
        try: cursor.execute("ALTER SEQUENCE adresse_id_seq RESTART WITH 1;")
        except: pass
        try: cursor.execute("ALTER SEQUENCE patient_id_seq RESTART WITH 1;")
        except: pass
        try: cursor.execute("ALTER SEQUENCE cas_maladie_id_seq RESTART WITH 1;")
        except: pass
        try: cursor.execute("ALTER SEQUENCE cluster_epidemique_id_seq RESTART WITH 1;")
        except: pass

        # Vérifier s'il y a un Centre de Santé disponible
        cursor.execute("SELECT id FROM centre_sante LIMIT 1;")
        centre_row = cursor.fetchone()
        if centre_row:
            id_centre_affectation = centre_row[0]
        else:
            print("❌ ERREUR: Aucun Centre de Santé n'existe.")
            return

        # Vérifier s'il y a un utilisateur
        cursor.execute("SELECT id FROM utilisateur WHERE id_role IN (2, 3) LIMIT 1;") 
        user_row = cursor.fetchone()
        id_utilisateur = user_row[0] if user_row else 1

        print("-> Génération des patients et des cas de choléra...")
        
        date_actuelle = datetime.now()
        cas_crees = 0

        for foyer in FOYERS:
            print(f"   - Génération de {foyer['nb_cas']} cas à {foyer['quartier']}...")
            
            for i in range(foyer['nb_cas']):
                # Coordonnées géographiques
                lat, lng = generer_point_aleatoire(foyer['lat'], foyer['lng'], foyer['rayon_m'])
                
                # Date d'enregistrement 
                jours_en_arriere = random.choices([0, 1, 2, 3, 4, 5, 6, 7], weights=[30, 20, 15, 10, 10, 5, 5, 5])[0]
                date_enreg = date_actuelle - timedelta(days=jours_en_arriere)
                
                # Insertion Adresse (Avec les mots exacts autorisés par la BD)
                cursor.execute("""
                    INSERT INTO adresse (commune, quartier, latitude, longitude, niveau_precision)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id;
                """, (foyer['commune'], foyer['quartier'], lat, lng, foyer['precision']))
                id_adresse = cursor.fetchone()[0]

                # Insertion Patient 
                sexe = random.choice(['M', 'F'])
                cursor.execute("""
                    INSERT INTO patient (nom, prenom, sexe, id_adresse)
                    VALUES (%s, 'Anonyme', %s, %s) RETURNING id;
                """, (f"Patient_{cas_crees}", sexe, id_adresse))
                id_patient = cursor.fetchone()[0]

                # Insertion Cas 
                statut = random.choice([1, 2])
                cursor.execute("""
                    INSERT INTO cas_maladie (date_enregistrement, id_patient, id_maladie, id_centre_sante, id_adresse, id_utilisateur, id_statut)
                    VALUES (%s, %s, 1, %s, %s, %s, %s) RETURNING id;
                """, (date_enreg, id_patient, id_centre_affectation, id_adresse, id_utilisateur, statut))

                cas_crees += 1

        conn.commit()
        print(f"\n✅ TERMINÉ : {cas_crees} cas ont été insérés dans la base de données avec succès.")

    except Exception as e:
        print(f"\n❌ Erreur lors de l'insertion : {str(e)}")
        if 'conn' in locals(): conn.rollback()
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    generer_epidemiologie()
