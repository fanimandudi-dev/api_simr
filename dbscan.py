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
MALADIE_ID = 1               
DISTANCE_METRES = 1500       # Tolérance IA augmentée à 1,5 km (au lieu de 450m)
MIN_CAS_POUR_ALERTE = 5      # Il faut au moins 5 cas regroupés pour faire un foyer
RAYON_TERRE_KM = 6371.0088

def haversine_distance(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1 
    dlon = lon2 - lon1 
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a)) 
    return (RAYON_TERRE_KM * c) * 1000

def executer_dbscan():
    print(f"\n[{datetime.now()}] 🔬 Démarrage de l'analyse IA (DBSCAN)...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # ÉTAPE A : Extraction (On prend TOUS les cas qui ont des coordonnées)
        query = """
            SELECT cas.id, adr.latitude, adr.longitude 
            FROM cas_maladie cas
            JOIN adresse adr ON cas.id_adresse = adr.id
            WHERE cas.id_maladie = %s 
            AND cas.date_enregistrement >= CURRENT_DATE - INTERVAL '30 days'
            AND adr.latitude IS NOT NULL; 
        """
        df_cas = pd.read_sql_query(query, conn, params=(MALADIE_ID,))
        
        if df_cas.empty: return print("-> Aucun cas trouvé.")
        print(f"-> {len(df_cas)} cas récupérés pour l'analyse spatiale.")

        # ÉTAPE B : Entraînement Machine Learning
        coords_radians = np.radians(df_cas[['latitude', 'longitude']].values)
        epsilon_radians = (DISTANCE_METRES / 1000.0) / RAYON_TERRE_KM

        db = DBSCAN(eps=epsilon_radians, min_samples=MIN_CAS_POUR_ALERTE, algorithm='ball_tree', metric='haversine')
        df_cas['cluster_label'] = db.fit_predict(coords_radians)

        # On nettoie l'ancienne table de liaison pour faire place au nouveau calcul
        cursor.execute("DELETE FROM cluster_cas;")
        cursor.execute("DELETE FROM cluster_epidemique;")

        # ÉTAPE C : Enregistrement des vrais Foyers (Clusters)
        clusters_trouves = df_cas[df_cas['cluster_label'] != -1]
        labels_uniques = clusters_trouves['cluster_label'].unique()
        
        print(f"🚨 {len(labels_uniques)} FOYERS (CLUSTERS) DÉTECTÉS PAR L'IA !")

        for label in labels_uniques:
            cas_du_cluster = clusters_trouves[clusters_trouves['cluster_label'] == label]
            liste_ids_cas = cas_du_cluster['id'].tolist()
            
            centre_lat = float(cas_du_cluster['latitude'].mean())
            centre_lon = float(cas_du_cluster['longitude'].mean())
            nombre_cas = len(cas_du_cluster)
            
            # Calcul du Rayon dynamique (Haversine)
            distances = [haversine_distance(centre_lat, centre_lon, row['latitude'], row['longitude']) for index, row in cas_du_cluster.iterrows()]
            rayon_estime = int(max(distances)) if distances else 0
            if rayon_estime < 250: rayon_estime = 300 # On force un rayon minimum pour que la carte soit belle
            
            # Sauvegarde du Foyer
            cursor.execute("""
                INSERT INTO cluster_epidemique (rayon_actuel, nombre_cas_actuel, centre_latitude_actuel, centre_longitude_actuel, id_maladie, id_statut)
                VALUES (%s, %s, %s, %s, %s, 3) RETURNING id;
            """, (rayon_estime, nombre_cas, centre_lat, centre_lon, MALADIE_ID))
            id_cluster_db = cursor.fetchone()[0]

            # Rattachement des patients au Foyer
            for cas_id in liste_ids_cas:
                cursor.execute("INSERT INTO cluster_cas (id_cluster, id_cas_maladie) VALUES (%s, %s)", (id_cluster_db, cas_id))

        conn.commit()
        print("✅ CALCUL TERMINÉ : Allez voir votre Carte Leaflet !")

    except Exception as e:
        print(f"❌ Erreur DBSCAN : {e}")
        if 'conn' in locals(): conn.rollback()
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    executer_dbscan()