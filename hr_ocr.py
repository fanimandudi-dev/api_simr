import os
import requests
import cv2
import numpy as np
import traceback
from dotenv import load_dotenv

# 1. Chargement des variables
load_dotenv()
HF_API_KEY = os.getenv("HF_API_KEY")

# 🌟 BYPASS DNS WINDOWS : On utilise l'adresse IP directe d'Hugging Face (54.210.15.111 / 34.225.120.40)
# Cela empêche l'erreur [Errno 11001] getaddrinfo failed sur l'ordinateur MANDUDI.
API_IP = "54.210.15.111" 
API_URL = f"https://{API_IP}/models/microsoft/trocr-base-handwritten"

def decouper_regions_interet(image_path: str):
    print("✂️ [OpenCV] Chargement et pré-traitement de l'image...")
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError("Impossible de lire l'image avec OpenCV.")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hauteur, largeur = img.shape[:2]
    
    regions = {
        "province": img[int(hauteur*0.05):int(hauteur*0.08), int(largeur*0.15):int(largeur*0.45)],
        "zone_sante": img[int(hauteur*0.08):int(hauteur*0.11), int(largeur*0.15):int(largeur*0.45)],
        "nom_complet": img[int(hauteur*0.25):int(hauteur*0.28), int(largeur*0.20):int(largeur*0.80)],
        "adresse_complete": img[int(hauteur*0.35):int(hauteur*0.40), int(largeur*0.15):int(largeur*0.90)],
        "date_consultation": img[int(hauteur*0.45):int(hauteur*0.48), int(largeur*0.20):int(largeur*0.50)],
        "maladie_suspectee": img[int(hauteur*0.60):int(hauteur*0.65), int(largeur*0.30):int(largeur*0.80)],
        "type_de_cas": img[int(hauteur*0.65):int(hauteur*0.68), int(largeur*0.30):int(largeur*0.80)],
    }
    
    cases_a_cocher = {
        "sexe_M": img[int(hauteur*0.30):int(hauteur*0.32), int(largeur*0.40):int(largeur*0.45)],
        "sexe_F": img[int(hauteur*0.30):int(hauteur*0.32), int(largeur*0.50):int(largeur*0.55)],
        "hospitalise_OUI": img[int(hauteur*0.75):int(hauteur*0.77), int(largeur*0.40):int(largeur*0.45)],
        "hospitalise_NON": img[int(hauteur*0.75):int(hauteur*0.77), int(largeur*0.50):int(largeur*0.55)],
        "decede_OUI": img[int(hauteur*0.80):int(hauteur*0.82), int(largeur*0.40):int(largeur*0.45)],
        "decede_NON": img[int(hauteur*0.80):int(hauteur*0.82), int(largeur*0.50):int(largeur*0.55)]
    }

    fichiers_decoupes = {}
    temp_dir = "temp_roi"
    os.makedirs(temp_dir, exist_ok=True)
    
    for nom_champ, region_img in regions.items():
        if region_img.size > 0:
            chemin_temp = os.path.join(temp_dir, f"roi_{nom_champ}.jpg")
            cv2.imwrite(chemin_temp, region_img)
            fichiers_decoupes[nom_champ] = chemin_temp
            
    resultats_cases = {}
    for nom_case, region_img in cases_a_cocher.items():
        if region_img.size > 0:
            _, binarized = cv2.threshold(cv2.cvtColor(region_img, cv2.COLOR_BGR2GRAY), 128, 255, cv2.THRESH_BINARY_INV)
            ratio_encre = cv2.countNonZero(binarized) / float(region_img.shape[0] * region_img.shape[1])
            resultats_cases[nom_case] = ratio_encre > 0.10

    return fichiers_decoupes, resultats_cases

def analyser_image_api(image_path: str) -> str:
    if not HF_API_KEY:
        print("⚠️ Simulation OCR (Pas de clé API).")
        return "Texte_Simulé"

    try:
        # 🌟 BYPASS DNS WINDOWS : On force le nom d'hôte dans le header pour que le certificat HTTPS l'accepte
        headers = {
            "Authorization": f"Bearer {HF_API_KEY}",
            "Host": "api-inference.huggingface.co"
        }

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        # verify=False empêche Python de rejeter l'IP directe (car le certificat est pour le nom de domaine)
        response = requests.post(API_URL, headers=headers, data=image_bytes, verify=False, timeout=20)

        if response.status_code == 200:
            resultat = response.json()
            if isinstance(resultat, list) and len(resultat) > 0 and 'generated_text' in resultat[0]:
                return resultat[0]['generated_text'].strip()
            return ""
                
        elif response.status_code == 503:
            print("⏳ Modèle TrOCR en démarrage (503).")
            return ""
            
        else:
            print(f"❌ Erreur HTTP Hugging Face [{response.status_code}] : {response.text}")
            return ""
            
    except requests.exceptions.ConnectionError:
        print("❌ Erreur Réseau (ConnectionError) : Votre ordinateur bloque l'accès à Hugging Face.")
        return ""
    except Exception as e:
        print(f"❌ Erreur inattendue [{type(e).__name__}] : {e}")
        return ""

def analyser_fiche_complete(image_path: str):
    print(f"\n🚀 DÉMARRAGE DU PIPELINE DE VISION SUR : {image_path}")
    
    # ÉTAPE 1 : Découpage par OpenCV
    fichiers_roi, resultats_cases = decouper_regions_interet(image_path)
    
    resultats_finaux = {}
    
    # ÉTAPE 2 : Inférence IA sur chaque petite zone TEXTUELLE
    print("\n🧠 [TrOCR] Analyse des zones manuscrites...")
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning) # Désactive l'avertissement de sécurité SSL local

    for nom_champ, chemin_temp in fichiers_roi.items():
        texte = analyser_image_api(chemin_temp)
        resultats_finaux[nom_champ] = texte
        print(f"   ✅ {nom_champ.upper()} détecté : {texte}")
        
        try: os.remove(chemin_temp)
        except: pass

    # ÉTAPE 3 : Intégration des résultats logiques (Cases à cocher d'OpenCV)
    print("\n🔍 [OpenCV] Analyse des cases à cocher...")
    resultats_finaux["sexe"] = "M" if resultats_cases.get("sexe_M") else ("F" if resultats_cases.get("sexe_F") else "Inconnu")
    resultats_finaux["hospitalise"] = "OUI" if resultats_cases.get("hospitalise_OUI") else "NON"
    resultats_finaux["decede"] = "OUI" if resultats_cases.get("decede_OUI") else "NON"
    
    print(f"   ✅ Sexe détecté : {resultats_finaux['sexe']}")
    print(f"   ✅ Hospitalisation : {resultats_finaux['hospitalise']}")
    print(f"   ✅ Décès : {resultats_finaux['decede']}")

    return resultats_finaux

if __name__ == "__main__":
    test_img = "Back_end/uploads/Gemini_Generated_Image_iw6nxgiw6nxgiw6n.png"
    if os.path.exists(test_img):
        analyser_fiche_complete(test_img)
    else:
        print("Aucune image test trouvée.")