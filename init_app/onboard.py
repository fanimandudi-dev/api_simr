import os
import psycopg2
from dotenv import load_dotenv

def seed_onboarding():
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ ERREUR: DATABASE_URL introuvable.")
        return

    print("🚀 Démarrage du Seeding Onboarding (Données de base)...")
    conn = None
    cursor = None

    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()

        print("   -> Insertion des Rôles Utilisateurs...")
        roles = [
            ("MCZ", "Médecin Chef de Zone (Administrateur)"),
            ("MEDECIN", "Médecin Superviseur de Centre"),
            ("INFIRMIER", "Infirmier Titulaire (Saisie)")
        ]
        cursor.executemany("INSERT INTO role_utilisateur (nom, description) VALUES (%s, %s) ON CONFLICT DO NOTHING;", roles)

        print("   -> Insertion de la Maladie de référence (Choléra)...")
        cursor.execute("""
            INSERT INTO maladie (code, nom, description) 
            VALUES ('CHL', 'Choléra', 'Infection diarrhéique aiguë') 
            ON CONFLICT DO NOTHING;
        """)

        print("   -> Insertion des Statuts Cliniques et IA...")
        statuts = [
            ("Suspect", "CAS_SUSPECT"),
            ("Confirmé", "CAS_CONFIRME"),
            ("Nouveau Cluster", "CLUSTER_NOUVEAU"),
            ("Sous contrôle", "CLUSTER_CONTROLE")
        ]
        cursor.executemany("INSERT INTO statut (nom, code) VALUES (%s, %s) ON CONFLICT DO NOTHING;", statuts)

        print("   -> Création du compte Super-Administrateur (MCZ)...")
        # On suppose que l'ID du rôle MCZ est 1 suite à l'insertion ci-dessus
        cursor.execute("""
            INSERT INTO utilisateur (nom_utilisateur, mot_de_passe, sexe, id_role)
            VALUES ('admin', 'admin', 'M', (SELECT id FROM role_utilisateur WHERE nom='MCZ'))
            ON CONFLICT DO NOTHING;
        """)

        conn.commit()
        print("✅ SUCCÈS : Données d'Onboarding insérées. L'application peut démarrer.")

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
    seed_onboarding()