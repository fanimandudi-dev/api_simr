import os
import psycopg2
from dotenv import load_dotenv

def reset_database():
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ ERREUR: DATABASE_URL introuvable dans le .env")
        return

    print("🔄 Démarrage de la réinitialisation de la base de données...")
    conn = None
    cursor = None

    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()

        # 1. Nettoyage radical (Supprime et recrée le schéma public)
        print("   -> Suppression de l'ancien schéma...")
        cursor.execute("DROP SCHEMA public CASCADE;")
        cursor.execute("CREATE SCHEMA public;")
        cursor.execute("GRANT ALL ON SCHEMA public TO postgres;")
        cursor.execute("GRANT ALL ON SCHEMA public TO public;")

        # 2. Création des tables
        print("   -> Création des tables...")
        schema_sql = """
        CREATE TABLE zone_sante (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(100) NOT NULL,
            code VARCHAR(50) NOT NULL UNIQUE,
            population INTEGER,
            province VARCHAR(100)
        );

        CREATE TABLE aire_sante (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(100) NOT NULL,
            population INTEGER,
            latitude NUMERIC(9,6),
            longitude NUMERIC(9,6),
            etat VARCHAR(20) DEFAULT 'ACTIF',
            id_zone_sante INTEGER NOT NULL
        );

        CREATE TABLE centre_sante (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(100) NOT NULL,
            commune VARCHAR(100),
            avenue VARCHAR(100),
            numero VARCHAR(20),
            type_centre VARCHAR(50),
            latitude NUMERIC(9,6),
            longitude NUMERIC(9,6),
            responsable VARCHAR(100),
            etat VARCHAR(20) DEFAULT 'ACTIF',
            id_aire_sante INTEGER NOT NULL
        );

        CREATE TABLE role_utilisateur (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(50) NOT NULL UNIQUE,
            description VARCHAR(255)
        );

        CREATE TABLE utilisateur (
            id SERIAL PRIMARY KEY,
            nom_utilisateur VARCHAR(50) NOT NULL UNIQUE,
            mot_de_passe VARCHAR(255) NOT NULL,
            sexe VARCHAR(10),
            telephone VARCHAR(20),
            creer_le TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            etat VARCHAR(20) DEFAULT 'ACTIF',
            id_role INTEGER NOT NULL,
            id_centre_sante INTEGER
        );

        CREATE TABLE adresse (
            id SERIAL PRIMARY KEY,
            commune VARCHAR(100),
            quartier VARCHAR(100),
            avenue VARCHAR(100),
            numero VARCHAR(20),
            latitude NUMERIC(9,6),
            longitude NUMERIC(9,6),
            date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            niveau_precision VARCHAR(30) DEFAULT 'INCONNU' NOT NULL
        );

        CREATE TABLE patient (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(50) NOT NULL,
            prenom VARCHAR(50) NOT NULL,
            post_nom VARCHAR(50),
            sexe VARCHAR(10),
            telephone VARCHAR(20),
            date_insertion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            id_adresse INTEGER
        );

        CREATE TABLE maladie (
            id SERIAL PRIMARY KEY,
            code VARCHAR(50) NOT NULL UNIQUE,
            nom VARCHAR(100) NOT NULL,
            description TEXT
        );

        CREATE TABLE statut (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(50) NOT NULL,
            code VARCHAR(50) NOT NULL UNIQUE
        );

        CREATE TABLE cas_maladie (
            id SERIAL PRIMARY KEY,
            date_enregistrement TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            id_patient INTEGER NOT NULL,
            id_maladie INTEGER NOT NULL,
            id_centre_sante INTEGER NOT NULL,
            id_adresse INTEGER NOT NULL,
            id_utilisateur INTEGER NOT NULL,
            id_statut INTEGER NOT NULL
        );

        CREATE TABLE symptome_cas (
            id SERIAL PRIMARY KEY,
            nom_symptome VARCHAR(100) NOT NULL,
            id_cas_maladie INTEGER NOT NULL
        );

        CREATE TABLE cluster_epidemique (
            id SERIAL PRIMARY KEY,
            date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            rayon_actuel NUMERIC(10,2),
            nombre_cas_actuel INTEGER,
            centre_latitude_actuel NUMERIC(9,6),
            centre_longitude_actuel NUMERIC(9,6),
            id_maladie INTEGER NOT NULL,
            id_statut INTEGER NOT NULL
        );

        CREATE TABLE cluster_cas (
            id SERIAL PRIMARY KEY,
            date_association TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            id_cluster INTEGER NOT NULL,
            id_cas_maladie INTEGER NOT NULL,
            UNIQUE (id_cluster, id_cas_maladie)
        );

        CREATE TABLE historique_cluster (
            id SERIAL PRIMARY KEY,
            date_calcul TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            rayon NUMERIC(10,2),
            nombre_cas INTEGER,
            centre_latitude NUMERIC(9,6),
            centre_longitude NUMERIC(9,6),
            id_cluster INTEGER NOT NULL
        );

        CREATE TABLE notification (
            id SERIAL PRIMARY KEY,
            titre VARCHAR(100) NOT NULL,
            message TEXT NOT NULL,
            type_alerte VARCHAR(50) DEFAULT 'INFO',
            role_cible VARCHAR(50) DEFAULT 'TOUS',
            est_lue BOOLEAN DEFAULT FALSE,
            date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            id_cluster INTEGER
        );
        """
        cursor.execute(schema_sql)

        # 3. Création des clés étrangères
        print("   -> Application des contraintes (Foreign Keys)...")
        fk_sql = """
        ALTER TABLE aire_sante ADD CONSTRAINT fk_aire_zone FOREIGN KEY (id_zone_sante) REFERENCES zone_sante(id) ON DELETE CASCADE;
        ALTER TABLE centre_sante ADD CONSTRAINT fk_centre_aire FOREIGN KEY (id_aire_sante) REFERENCES aire_sante(id) ON DELETE RESTRICT;
        ALTER TABLE utilisateur ADD CONSTRAINT fk_user_role FOREIGN KEY (id_role) REFERENCES role_utilisateur(id) ON DELETE RESTRICT;
        ALTER TABLE utilisateur ADD CONSTRAINT fk_user_centre FOREIGN KEY (id_centre_sante) REFERENCES centre_sante(id) ON DELETE RESTRICT;
        ALTER TABLE patient ADD CONSTRAINT fk_patient_adresse FOREIGN KEY (id_adresse) REFERENCES adresse(id) ON DELETE SET NULL;
        ALTER TABLE cas_maladie ADD CONSTRAINT fk_cas_patient FOREIGN KEY (id_patient) REFERENCES patient(id) ON DELETE CASCADE;
        ALTER TABLE cas_maladie ADD CONSTRAINT fk_cas_maladie FOREIGN KEY (id_maladie) REFERENCES maladie(id) ON DELETE RESTRICT;
        ALTER TABLE cas_maladie ADD CONSTRAINT fk_cas_centre FOREIGN KEY (id_centre_sante) REFERENCES centre_sante(id) ON DELETE RESTRICT;
        ALTER TABLE cas_maladie ADD CONSTRAINT fk_cas_adresse FOREIGN KEY (id_adresse) REFERENCES adresse(id) ON DELETE RESTRICT;
        ALTER TABLE cas_maladie ADD CONSTRAINT fk_cas_user FOREIGN KEY (id_utilisateur) REFERENCES utilisateur(id) ON DELETE RESTRICT;
        ALTER TABLE cas_maladie ADD CONSTRAINT fk_cas_statut FOREIGN KEY (id_statut) REFERENCES statut(id) ON DELETE RESTRICT;
        ALTER TABLE symptome_cas ADD CONSTRAINT fk_sympt_cas FOREIGN KEY (id_cas_maladie) REFERENCES cas_maladie(id) ON DELETE CASCADE;
        ALTER TABLE cluster_epidemique ADD CONSTRAINT fk_cluster_maladie FOREIGN KEY (id_maladie) REFERENCES maladie(id) ON DELETE CASCADE;
        ALTER TABLE cluster_epidemique ADD CONSTRAINT fk_cluster_statut FOREIGN KEY (id_statut) REFERENCES statut(id) ON DELETE RESTRICT;
        ALTER TABLE cluster_cas ADD CONSTRAINT fk_cc_cluster FOREIGN KEY (id_cluster) REFERENCES cluster_epidemique(id) ON DELETE CASCADE;
        ALTER TABLE cluster_cas ADD CONSTRAINT fk_cc_cas FOREIGN KEY (id_cas_maladie) REFERENCES cas_maladie(id) ON DELETE CASCADE;
        ALTER TABLE historique_cluster ADD CONSTRAINT fk_hist_cluster FOREIGN KEY (id_cluster) REFERENCES cluster_epidemique(id) ON DELETE CASCADE;
        ALTER TABLE notification ADD CONSTRAINT fk_notif_cluster FOREIGN KEY (id_cluster) REFERENCES cluster_epidemique(id) ON DELETE CASCADE;
        """
        cursor.execute(fk_sql)

        conn.commit()
        print("✅ SUCCÈS : Base de données réinitialisée avec le schéma complet.")

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
    reset_database()