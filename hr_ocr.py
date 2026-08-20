import os
import requests
import re
import traceback

def analyser_image_api(image_path: str) -> str:
    """Envoie la fiche entière à l'API publique OCR.space."""
    print("🚀 Appel API Cloud (OCR.space)...")
    try:
        API_URL = "https://api.ocr.space/parse/image"
        payload = {
            'apikey': 'helloworld',
            'language': 'fre', # Français
            'scale': 'true',
            'OCREngine': '2'   # Moteur 2 optimisé pour les PDF et formulaires
        }
        
        with open(image_path, "rb") as f:
            response = requests.post(
                API_URL, 
                files={'file': f},
                data=payload,
                timeout=30
            )

        if response.status_code == 200:
            resultat = response.json()
            if not resultat.get("IsErroredOnProcessing") and resultat.get("ParsedResults"):
                texte_predit = resultat["ParsedResults"][0]["ParsedText"]
                # On remplace les sauts de lignes multiples par un espace propre
                texte_propre = " ".join(texte_predit.split())
                print(f"✅ OCR Terminé avec succès.")
                return texte_propre
            else:
                print(f"⚠️ Erreur de lecture OCR : {resultat.get('ErrorMessage')}")
                return ""
        else:
            print(f"❌ Erreur HTTP OCR.space [{response.status_code}]")
            return ""
    except Exception as e:
        print(f"❌ Erreur globale d'Inférence : {e}")
        return ""

def extraire_donnees_regex(texte: str):
    """
    Parcourt le texte brut de l'OCR pour extraire intelligemment les champs du formulaire SIMR.
    """
    resultats = {}

    # Extraction de la Province
    match_province = re.search(r"Province[\s:]*([A-Za-z]+)", texte, re.IGNORECASE)
    resultats["province"] = match_province.group(1).strip() if match_province else ""

    # Extraction de la Zone de Santé
    match_zone = re.search(r"Zone de santé[\s:]*([A-Za-z\s]+)(?:•|Aire)", texte, re.IGNORECASE)
    resultats["zone_sante"] = match_zone.group(1).strip() if match_zone else ""

    # 🌟 NOUVEAU : Extraction de la Structure de Santé
    match_structure = re.search(r"Structure de santé[\s:]*([A-Za-z\s]+)(?:•|Date)", texte, re.IGNORECASE)
    resultats["structure_sante"] = match_structure.group(1).strip() if match_structure else ""

    # Extraction du Nom Complet
    match_nom = re.search(r"Nom complet[\s:]*([A-Za-z\s]+)(?:•|Sexe)", texte, re.IGNORECASE)
    resultats["nom_complet"] = match_nom.group(1).strip() if match_nom else ""

    # Extraction du Sexe (M ou F)
    match_sexe = re.search(r"Sexe[\s:]*([MF])", texte, re.IGNORECASE)
    resultats["sexe"] = match_sexe.group(1).upper() if match_sexe else "M"

    # Extraction de l'Adresse Complète
    match_adresse = re.search(r"Adresse complète[\s:]*(.+?)(?:•|Aire)", texte, re.IGNORECASE)
    resultats["adresse_complete"] = match_adresse.group(1).strip() if match_adresse else ""

    # Extraction de la Maladie
    match_maladie = re.search(r"Maladie ou syndrome suspecté[\s:]*(.+?)(?:•|Type)", texte, re.IGNORECASE)
    maladie_brute = match_maladie.group(1).replace(".", "").strip() if match_maladie else ""
    resultats["maladie_suspectee"] = maladie_brute

    # 🌟 NOUVEAU : Extraction du Type de cas (Résultats de laboratoire)
    # L'OCR a lu "CON FIRME", on le nettoie pour envoyer "Confirmé" à Angular
    match_type = re.search(r"Résultats de laboratoire[\s:]*([A-Za-z\s]+)\.", texte, re.IGNORECASE)
    type_brut = match_type.group(1).replace(" ", "").upper() if match_type else ""
    if "FIRME" in type_brut:
        resultats["type_de_cas"] = "Confirmé"
    elif "SUSPECT" in type_brut:
        resultats["type_de_cas"] = "Suspect"
    else:
        resultats["type_de_cas"] = "Non défini"

    # Analyse des Cases à Cocher (OUI / NON)
    resultats["hospitalise"] = "NON"
    if "Hospitalisé : D Oui" in texte or "Hospitalisé : Oui" in texte:
        resultats["hospitalise"] = "OUI"

    resultats["decede"] = "NON"
    if "@Non" in texte or "Non Décédé" in texte:
        resultats["decede"] = "NON"
    elif "Décédé : Oui" in texte or "Décédé : O Oui" in texte:
        resultats["decede"] = "OUI"

    return resultats

def analyser_fiche_complete(image_path: str):
    print(f"\n🚀 DÉMARRAGE DU PIPELINE OCR SUR : {image_path}")
    
    # Étape 1 : Lire toute l'image d'un coup
    texte_brut = analyser_image_api(image_path)
    
    if not texte_brut:
        print("❌ Impossible de lire le document.")
        return {}

    # Étape 2 : Extraire les données métier
    print("\n🔍 Extraction intelligente des données...")
    donnees_extraites = extraire_donnees_regex(texte_brut)

    # Affichage des résultats pour le terminal
    print("\n--- RÉSULTATS POUR LE FORMULAIRE ANGULAR ---")
    for cle, valeur in donnees_extraites.items():
        print(f"✅ {cle.upper()} : {valeur}")

    return donnees_extraites

# TEST LOCAL
if __name__ == "__main__":
    test_img = "Back_end/uploads/fiche_1.jpeg" # Remplacez par le nom de l'image (jpeg/png) de votre test
    # (OCR.space lit aussi les PDF directs !)
    if os.path.exists(test_img):
        analyser_fiche_complete(test_img)
    else:
        print("Aucune image/pdf test trouvée.")