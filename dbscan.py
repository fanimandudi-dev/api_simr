import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from sklearn.cluster import DBSCAN
from datetime import datetime
import warnings

warnings.filterwarnings("ignore", category=UserWarning)

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# --- NOUVEAUX PARAMÈTRES IA (Plus tolérants) ---
MALADIE_ID = 1               # 1 = Choléra
DISTANCE_METRES = 450        # Epsilon : Rayon de voisinage spatial (450m)
MIN_CAS_POUR_ALERTE = 3      # MinPts : Nombre de cas requis pour former un foyer
RAYON_TERRE_KM = 6371.0088   # Constante pour Haversine

def haversine_distance(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1 
    dlon = lon2 - lon1 
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a)) 
    return (RAYON_TERRE_KM * c) * 1000

# ==========================================
# 2. EXÉCUTION DU MACHINE LEARNING (DBSCAN)
# ==========================================
def executer_dbscan():
    print(f"\n[{datetime.now()}] 🔬 Démarrage de l'analyse IA (DBSCAN)...")
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # ÉTAPE A : EXTRACTION & FILTRAGE (On exclut le niveau INCONNU)
        query = """
            SELECT cas.id, adr.latitude, adr.longitude, adr.niveau_precision 
            FROM cas_maladie cas
            JOIN adresse adr ON cas.id_adresse = adr.id
            WHERE cas.id_maladie = %s 
            AND cas.date_enregistrement >= CURRENT_DATE - INTERVAL '30 days'
            AND adr.niveau_precision != 'INCONNU'; 
        """
        df_cas = pd.read_sql_query(query, conn, params=(MALADIE_ID,))
        
        if df_cas.empty:
            print("   -> Aucun cas géolocalisable avec précision trouvé.")
            return

        print(f"   -> {len(df_cas)} cas précis récupérés pour l'analyse spatiale.")

        # ÉTAPE B : ENTRAÎNEMENT DU MODÈLE
        coords_radians = np.radians(df_cas[['latitude', 'longitude']].values)
        epsilon_radians = (DISTANCE_METRES / 1000.0) / RAYON_TERRE_KM

        db = DBSCAN(eps=epsilon_radians, min_samples=MIN_CAS_POUR_ALERTE, algorithm='ball_tree', metric='haversine')
        df_cas['cluster_label'] = db.fit_predict(coords_radians)

        # ÉTAPE C : TRAITEMENT RÉSULTATS
        clusters_trouves = df_cas[df_cas['cluster_label'] != -1]
        labels_uniques = clusters_trouves['cluster_label'].unique()
        
        print(f"   🚨 {len(labels_uniques)} foyers épidémiques (clusters) détectés.")

        for label in labels_uniques:
            cas_du_cluster = clusters_trouves[clusters_trouves['cluster_label'] == label]
            liste_ids_cas = cas_du_cluster['id'].tolist()
            
            centre_lat = float(cas_du_cluster['latitude'].mean())
            centre_lon = float(cas_du_cluster['longitude'].mean())
            nombre_cas = len(cas_du_cluster)
            
            distances = [haversine_distance(centre_lat, centre_lon, row['latitude'], row['longitude']) for index, row in cas_du_cluster.iterrows()]
            rayon_estime = int(max(distances)) if distances else 0
            if rayon_estime < 50: rayon_estime = 100 

            cursor.execute("""
                SELECT id_cluster FROM cluster_cas 
                WHERE id_cas_maladie = ANY(%s) 
                LIMIT 1;
            """, (liste_ids_cas,))
            
            resultat_existant = cursor.fetchone()

            if resultat_existant:
                id_cluster_db = resultat_existant[0]
                print(f"      🔄 Foyer existant #{id_cluster_db} mis à jour ({nombre_cas} cas).")
                
                cursor.execute("""
                    UPDATE cluster_epidemique 
                    SET rayon_actuel = %s, nombre_cas_actuel = %s, 
                        centre_latitude_actuel = %s, centre_longitude_actuel = %s
                    WHERE id = %s;
                """, (rayon_estime, nombre_cas, centre_lat, centre_lon, id_cluster_db))
            else:
                print(f"      ⚠️ NOUVELLE ALERTE : Foyer avec {nombre_cas} cas.")
                
                cursor.execute("""
                    INSERT INTO cluster_epidemique 
                    (rayon_actuel, nombre_cas_actuel, centre_latitude_actuel, centre_longitude_actuel, id_maladie, id_statut)
                    VALUES (%s, %s, %s, %s, %s, 3) RETURNING id;
                """, (rayon_estime, nombre_cas, centre_lat, centre_lon, MALADIE_ID))
                
                id_cluster_db = cursor.fetchone()[0]

                # 🌟 NOUVEAU : Envoi d'une notification Push au MCZ
                cursor.execute("""
                    INSERT INTO notification (titre, message, type_alerte, role_cible)
                    VALUES (%s, %s, 'URGENCE', 'MCZ')
                """, ("NOUVEAU FOYER DÉTECTÉ", f"L'algorithme IA a identifié un nouveau cluster épidémique actif dans votre zone avec {nombre_cas} cas détectés."))

            for cas_id in liste_ids_cas:
                cursor.execute("""
                    INSERT INTO cluster_cas (id_cluster, id_cas_maladie) 
                    VALUES (%s, %s)
                    ON CONFLICT (id_cluster, id_cas_maladie) DO NOTHING;
                """, (id_cluster_db, cas_id))

        conn.commit()
        print("   ✅ Modélisation spatiale sauvegardée.\n")

    except Exception as e:
        print(f"   ❌ Erreur critique DBSCAN : {e}")
        if 'conn' in locals(): conn.rollback()
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    executer_dbscan()