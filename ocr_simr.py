import cv2
import pytesseract
from pytesseract import Output
import numpy as np

print("OCR SIMR module chargé avec succès.")

# Chemin vers l'exécutable Tesseract sur Windows
pytesseract.pytesseract.tesseract_cmd = r'C:\Tesseract-OCR\tesseract.exe'

def traiter_image_simr(image_path: str):
    """
    Traite une image de fiche SIMR, extrait le texte et calcule le score de confiance.
    """
    print(f"--- Début du traitement OCR pour : {image_path} ---")
    
    # 1. Charger l'image avec OpenCV
    img = cv2.imread(image_path)
    
    if img is None:
        print(f"❌ Échec du chargement de l'image pour : {image_path}")
        raise ValueError("Impossible de charger l'image. L'image est peut-être corrompue ou le chemin est incorrect.")
    
    print(f"✅ Image chargée avec succès ! Dimensions : {img.shape}")

    # 2. Pré-traitement de l'image (Crucial pour un bon OCR)
    try:
        # Passer en niveaux de gris
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Binarisation (Contraste maximal) - CORRECTION DE LA FAUTE ICI
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        print("✅ Pré-traitement de l'image (OpenCV) réussi.")
    except Exception as e:
        raise Exception(f"Erreur OpenCV lors du pré-traitement : {str(e)}")

    # 3. Extraction des données avec Tesseract
    custom_config = r'--oem 3 --psm 6'
    
    try:
        donnees_ocr = pytesseract.image_to_data(thresh, output_type=Output.DICT, config=custom_config, lang='fra')
        print("✅ Tesseract a lu l'image avec succès.")
    except Exception as e:
        raise Exception(f"Erreur Tesseract (vérifie que le pack Français 'fra' est installé) : {str(e)}")

    # 4. Traitement des résultats
    texte_complet = ""
    scores_confiance = []

    for i in range(len(donnees_ocr['text'])):
        mot = donnees_ocr['text'][i].strip()
        confiance = int(donnees_ocr['conf'][i])

        if mot != "": 
            texte_complet += mot + "\n" # On ajoute un saut de ligne après chaque mot
            if confiance > 0: 
                scores_confiance.append(confiance)

    # 5. Calcul de la confiance moyenne
    confiance_moyenne = sum(scores_confiance) / len(scores_confiance) if scores_confiance else 0.0

    print(f"✅ Extraction terminée. Confiance moyenne : {round(confiance_moyenne, 2)}%")
    print(f"Texte extrait :\n{texte_complet.strip()}")
    
    return {
        "texte_extrait": texte_complet.strip(),
        "confiance_moyenne": round(confiance_moyenne, 2)
    }