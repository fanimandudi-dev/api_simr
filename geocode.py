import requests
import random
import math
import time

# Constantes pour l'API Photon
# On utilise un User-Agent personnalisé par courtoisie
HEADERS = {
    'User-Agent': 'SIMR_App_TFE_Project/1.0'
}

def appliquer_jitter_spherique(lat_centre: float, lng_centre: float, rayon_max_metres: int) -> tuple:
    """
    Applique une dispersion spatiale aléatoire (Jitter) autour d'un point central.
    Utilise la trigonométrie sphérique pour garantir une distribution uniforme dans un cercle parfait.
    """
    u = random.random()
    v = random.random()
    rayon_aleatoire = rayon_max_metres * math.sqrt(u)
    angle_aleatoire = 2 * math.pi * v

    RAYON_TERRE_METRES = 6378137.0

    delta_lat = (rayon_aleatoire * math.cos(angle_aleatoire)) / RAYON_TERRE_METRES
    delta_lng = (rayon_aleatoire * math.sin(angle_aleatoire)) / (RAYON_TERRE_METRES * math.cos(math.radians(lat_centre)))

    nouvelle_lat = lat_centre + math.degrees(delta_lat)
    nouvelle_lng = lng_centre + math.degrees(delta_lng)

    return nouvelle_lat, nouvelle_lng

def obtenir_coordonnees(avenue: str, quartier: str, commune: str, lat_gps: float = None, lng_gps: float = None) -> dict:
    """
    Service de géocodage à 1 Niveau d'Appel (API OSM Photon) avec traitements différenciés selon la réponse.
    """
    
    # Si le GPS est fourni depuis l'appareil, on bypass l'API. C'est la donnée absolue.
    if lat_gps is not None and lng_gps is not None:
        return {"lat": lat_gps, "lng": lng_gps, "precision": "GPS_EXACT"}

    avenue_clean = avenue.strip() if avenue else ""
    quartier_clean = quartier.strip() if quartier else ""
    commune_clean = commune.strip() if commune else ""
    
    base_city = "Kinshasa"
    
    print(f"\n🌍 [Géocodage] Recherche API pour : '{avenue_clean}, {quartier_clean}, {commune_clean}'")

    # --- STRATÉGIE DE RECHERCHE EN CASCADE VERS L'API ---
    queries = []
    
    if avenue_clean and commune_clean:
        queries.append({"q": f"{avenue_clean} {commune_clean} {base_city}", "precision": "ADRESSE", "jitter": 0})
        
    if quartier_clean and commune_clean:
        queries.append({"q": f"{quartier_clean} {commune_clean} {base_city}", "precision": "QUARTIER", "jitter": 400})
        
    if commune_clean:
        queries.append({"q": f"{commune_clean} {base_city}", "precision": "COMMUNE", "jitter": 1500})


    # --- EXÉCUTION DES REQUÊTES ---
    for recherche in queries:
        print(f"   -> Tentative API : {recherche['q']}")
        try:
            url = f"https://photon.komoot.io/api/?q={recherche['q']}&limit=1"
            response = requests.get(url, headers=HEADERS, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                
                if data and "features" in data and len(data["features"]) > 0:
                    coords = data["features"][0]["geometry"]["coordinates"]
                    lng_api, lat_api = coords[0], coords[1]
                    
                    print(f"   ✅ Succès OSM ({recherche['precision']}) : Lat {lat_api}, Lng {lng_api}")
                    
                    # --- NIVEAUX DE TRAITEMENT (JITTER) ---
                    if recherche['jitter'] > 0:
                        lat_final, lng_final = appliquer_jitter_spherique(lat_api, lng_api, recherche['jitter'])
                        print(f"   📐 Jitter mathématique appliqué (Rayon: {recherche['jitter']}m)")
                    else:
                        lat_final, lng_final = lat_api, lng_api

                    return {
                        "lat": round(lat_final, 6),
                        "lng": round(lng_final, 6),
                        "precision": recherche['precision']
                    }
                    
        except Exception as e:
            print(f"   ❌ Erreur API : {e}")
            
        time.sleep(0.5) # Pause pour ne pas spammer le serveur gratuit

    # --- FALLBACK SI L'API NE TROUVE RIEN ---
    print("   ⚠️ Adresse introuvable par l'API. Fallback sur le centre de Kinshasa.")
    # On met au centre de Kinshasa avec un Jitter énorme de 3km pour marquer l'incertitude
    lat_fallback, lng_fallback = appliquer_jitter_spherique(-4.3224, 15.3070, 3000)
    
    return {
        "lat": round(lat_fallback, 6),
        "lng": round(lng_fallback, 6),
        "precision": "INCONNU"
    }

# --- TEST ---
if __name__ == "__main__":
    # Devrait trouver Niveau 1 : ADRESSE (Pas de Jitter)
    print("Test 1 :", obtenir_coordonnees("Boulevard du 30 Juin", "", "Limete"))
    
    # Devrait trouver Niveau 2 : QUARTIER (Jitter de 400m)
    print("Test 2 :", obtenir_coordonnees("", "Mombele", "Limete"))
    
    # Test avec des coordonnées GPS brutes (Niveau 1 absolu)
    print("Test 3 :", obtenir_coordonnees("Av Fausse", "Q Faux", "Commune", lat_gps=-4.320, lng_gps=15.310))

