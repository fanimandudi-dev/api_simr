from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import shutil
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import traceback

DATABASE_URL = os.getenv("DATABASE_URL")
load_dotenv()

# Importation de tes modules d'Intelligence Artificielle
import geocode
import ocr_simr


# Import de APScheduler pour les tâches cron en arrière-plan
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager

# ==========================================
# CONFIGURATION BASE DE DONNÉES
# ==========================================


def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# ==========================================
# CRON JOB (Tâches planifiées)
# ==========================================
def tache_planifiee_dbscan():
    print(f"[{datetime.now()}] CRON JOB : Lancement automatique de l'algorithme DBSCAN...")
    try:
        import dbscan
        dbscan.executer_dbscan()
        print("CRON JOB : Analyse DBSCAN terminée avec succès.")
    except Exception as e:
        print(f"CRON JOB : Erreur lors de l'exécution de DBSCAN - {str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(tache_planifiee_dbscan, 'interval', hours=0.5, id='job_dbscan')
    scheduler.start()
    print("Le planificateur de tâches (CRON) a été démarré. DBSCAN tournera toutes les 4 heures.")
    yield 
    scheduler.shutdown()
    print("Planificateur de tâches arrêté.")


# ==========================================
# INITIALISATION FASTAPI
# ==========================================
app = FastAPI(
    title="SIMR App - Backend API",
    description="API pour le Système d'Information de Surveillance Épidémiologique",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# ROUTES : AUTHENTIFICATION & STATUT SYSTÈME
# ==========================================


@app.post("/api/admin/trigger-dbscan")
async def trigger_dbscan_manually():
    try:
        import dbscan
        dbscan.executer_dbscan()
        return {"message": "Algorithme DBSCAN exécuté avec succès."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



class LoginData(BaseModel):
    login: str
    mdp: str

@app.post("/api/auth/login")
async def login(credentials: LoginData):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT u.id, u.nom_utilisateur, u.etat, r.nom as nom_role, 
                   u.id_centre_sante,
                   c.nom as nom_centre,
                   (SELECT id FROM zone_sante LIMIT 1) as id_zone,
                   (SELECT nom FROM zone_sante LIMIT 1) as nom_zone,
                   c.etat as etat_centre, a.etat as etat_aire
            FROM utilisateur u
            JOIN role_utilisateur r ON u.id_role = r.id
            LEFT JOIN centre_sante c ON u.id_centre_sante = c.id
            LEFT JOIN aire_sante a ON c.id_aire_sante = a.id
            WHERE u.nom_utilisateur = %s AND u.mot_de_passe = %s;
        """, (credentials.login, credentials.mdp))
        
        user_db = cursor.fetchone()
        
        if not user_db:
            raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect.")
            
        if user_db['etat'] != 'ACTIF':
            raise HTTPException(status_code=403, detail="Ce compte a été désactivé.")
            
        if user_db['nom_role'] != 'MCZ':
            if user_db['etat_centre'] == 'INACTIF' or user_db['etat_aire'] == 'INACTIF':
                raise HTTPException(status_code=403, detail="Accès refusé : Votre centre ou aire de santé a été fermé ou désactivé par l'administration.")

        return {
            "token": f"token_{user_db['id']}_{user_db['nom_role']}",
            "utilisateur": {
                "id": user_db['id'],
                "login": user_db['nom_utilisateur'],
                "role": user_db['nom_role'],
                "id_centre_sante": user_db['id_centre_sante'],
                "nom_centre": user_db['nom_centre'] or "Aucun",
                "id_zone": user_db['id_zone'] or 0,
                "zone": user_db['nom_zone'] or "Zone non configurée"
            }
        }
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()        
        
@app.get("/api/system-status")
async def get_system_status():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM zone_sante;")
        count = cursor.fetchone()[0]
        return {"isConfigured": count > 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()


# ==========================================
# ROUTES : TABLEAU DE BORD & CARTOGRAPHIE
# =========================================@app.get("/api/dashboard/stats")
@app.get("/api/dashboard/stats")
async def get_dashboard_stats(role: str = 'MCZ', id_centre: int = 0):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        if role == 'MCZ':
            # === OPTIMISATION : 1 SEULE REQUÊTE POUR L'ADMIN MCZ ===
            cursor.execute("""
                SELECT 
                    (SELECT COUNT(id) FROM cas_maladie 
                     WHERE date_enregistrement >= CURRENT_DATE - INTERVAL '7 days') as nouveaux_cas,
                     
                    (SELECT COUNT(id) FROM cluster_epidemique 
                     WHERE id_statut = 3) as clusters_actifs,
                     
                    (SELECT COUNT(id) FROM cas_maladie 
                     WHERE id_statut = 1) as fiches_attente_validation; 
            """)
            stats = cursor.fetchone()
            
            return {
                "nouveauxCas": stats['nouveaux_cas'] or 0,
                "clustersActifs": stats['clusters_actifs'] or 0,
                "fichesAttente": stats['fiches_attente_validation'] or 0
            }
            
        else:
            # === OPTIMISATION : 1 SEULE REQUÊTE POUR LE MÉDECIN/INFIRMIER ===
            cursor.execute("""
                SELECT 
                    -- Cas soumis aujourd'hui
                    COUNT(c.id) FILTER (WHERE DATE(c.date_enregistrement) = CURRENT_DATE) as cas_aujourdhui,
                    
                    -- Cas soumis cette semaine
                    COUNT(c.id) FILTER (WHERE c.date_enregistrement >= CURRENT_DATE - INTERVAL '7 days') as cas_semaine,
                    
                    -- Taux de saisies de haute qualité (Niveau 1 ou 2)
                    COALESCE(
                        ROUND(
                            (COUNT(c.id) FILTER (WHERE a.niveau_precision IN ('GPS_EXACT', 'ADRESSE')) * 100.0) 
                            / NULLIF(COUNT(c.id), 0)
                        ), 0
                    ) as taux_precision
                FROM cas_maladie c
                LEFT JOIN adresse a ON c.id_adresse = a.id
                WHERE c.id_centre_sante = %s;
            """, (id_centre,))
            
            stats = cursor.fetchone()
            
            return {
                "casSoumisAujourdhui": stats['cas_aujourdhui'] or 0,
                "casSoumisSemaine": stats['cas_semaine'] or 0,
                "tauxSaisieReussie": stats['taux_precision']
            }
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
        
@app.get("/api/map/clusters")
async def get_map_clusters():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. On récupère les clusters actifs
        cursor.execute("""
            SELECT c.id, c.rayon_actuel as rayon, c.nombre_cas_actuel as cas, 
                   c.centre_latitude_actuel as lat, c.centre_longitude_actuel as lng,
                   s.nom as statut, 'Zone Inconnue' as zone
            FROM cluster_epidemique c
            JOIN statut s ON c.id_statut = s.id;
        """)
        clusters = cursor.fetchall()
        
        # 2. On récupère les cas isolés (Bruit DBSCAN) 
        # C'est-à-dire les cas qui NE SONT PAS rattachés à un cluster dans la table cluster_cas
        cursor.execute("""
            SELECT cm.id, a.latitude as lat, a.longitude as lng 
            FROM cas_maladie cm
            JOIN adresse a ON cm.id_adresse = a.id
            WHERE cm.id NOT IN (SELECT id_cas_maladie FROM cluster_cas)
            AND a.niveau_precision != 'INCONNU'
            AND cm.date_enregistrement >= CURRENT_DATE - INTERVAL '30 days';
        """)
        bruit = cursor.fetchall()
        
        # 🌟 On renvoie un Objet contenant les 2 tableaux !
        return {
            "clusters": clusters,
            "bruit": bruit
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
# ==========================================
# ROUTES : ADMINISTRATION PYRAMIDE
# ==========================================
class ZoneSanteCreate(BaseModel):
    nom: str
    code: str
    province: str
    population: Optional[int] = 0

@app.post("/api/admin/zones")
async def creer_zone_sante(zone: ZoneSanteCreate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO zone_sante (nom, code, province, population)
            VALUES (%s, %s, %s, %s) RETURNING id;
        """, (zone.nom, zone.code, zone.province, zone.population))
        new_id = cursor.fetchone()[0]
        conn.commit()
        return {"message": "Zone de santé créée", "id": new_id}
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.put("/api/admin/zones/{zone_id}")
async def modifier_zone_sante(zone_id: int, zone: ZoneSanteCreate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE zone_sante 
            SET nom = %s, code = %s, province = %s, population = %s
            WHERE id = %s;
        """, (zone.nom, zone.code, zone.province, zone.population, zone_id))
        conn.commit()
        return {"message": "Zone de santé mise à jour !"}
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.get("/api/admin/zones")
async def get_zones_sante():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, nom, code, province, population FROM zone_sante ORDER BY nom;")
        return cursor.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

class AireSanteCreate(BaseModel):
    nom: str
    population: Optional[int] = 0
    id_zone_sante: int 

@app.post("/api/admin/aires")
async def creer_aire_sante(aire: AireSanteCreate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO aire_sante (nom, population, id_zone_sante, etat)
            VALUES (%s, %s, %s, 'ACTIF') RETURNING id;
        """, (aire.nom, aire.population, aire.id_zone_sante))
        new_id = cursor.fetchone()[0]
        conn.commit()
        return {"message": "Aire de santé créée", "id": new_id, "nom": aire.nom, "population": aire.population}
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.put("/api/admin/aires/{aire_id}")
async def modifier_aire_sante(aire_id: int, aire: AireSanteCreate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE aire_sante 
            SET nom = %s, population = %s
            WHERE id = %s AND etat = 'ACTIF';
        """, (aire.nom, aire.population, aire_id))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Aire introuvable ou inactive.")
            
        conn.commit()
        return {"message": "Aire de santé mise à jour !"}
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.get("/api/admin/aires")
async def get_aires_sante(zone_id: Optional[int] = None):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if zone_id:
            cursor.execute("SELECT id, nom, population FROM aire_sante WHERE id_zone_sante = %s AND etat = 'ACTIF' ORDER BY nom;", (zone_id,))
        else:
            cursor.execute("SELECT id, nom, population FROM aire_sante WHERE etat = 'ACTIF' ORDER BY nom;")
        return cursor.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
        
        

        

@app.delete("/api/admin/aires/{aire_id}")
async def supprimer_aire_sante(aire_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # LOGIQUE MÉTIER : Vérifier si des centres ACTIFS sont liés à cette aire
        cursor.execute("SELECT COUNT(*) FROM centre_sante WHERE id_aire_sante = %s AND etat = 'ACTIF';", (aire_id,))
        nb_centres = cursor.fetchone()[0]

        if nb_centres > 0:
            # ⛔ Refus formel de désactiver l'aire s'il y a des hôpitaux dedans
            raise HTTPException(status_code=400, detail=f"Impossible de supprimer : Cette aire contient encore {nb_centres} centre(s) de santé actif(s). Veuillez d'abord supprimer ou déplacer ces centres.")
        else:
            # On vérifie si la DB bloque quand même (ex: il y avait de vieux centres INACTIFS)
            try:
                cursor.execute("DELETE FROM aire_sante WHERE id = %s;", (aire_id,))
                message = "Aire de santé supprimée définitivement."
            except psycopg2.errors.ForeignKeyViolation:
                # Si on ne peut pas faire un DELETE, on fait un SOFT DELETE (Désactivation)
                conn.rollback()
                cursor = conn.cursor()
                cursor.execute("UPDATE aire_sante SET etat = 'INACTIF' WHERE id = %s;", (aire_id,))
                message = "L'aire a été désactivée (Conserve un historique médical caché)."

        conn.commit()
        return {"message": message}
    except HTTPException as he:
        raise he
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

class CentreSanteCreate(BaseModel):
    nom: str
    type_centre: str
    id_aire_sante: int
@app.post("/api/admin/centres")
async def creer_centre_sante(centre: CentreSanteCreate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Ajout du centre avec l'état 'ACTIF' par défaut
        cursor.execute("""
            INSERT INTO centre_sante (nom, type_centre, id_aire_sante, etat)
            VALUES (%s, %s, %s, 'ACTIF') RETURNING id;
        """, (centre.nom, centre.type_centre, centre.id_aire_sante))
        new_id = cursor.fetchone()[0]
        
        cursor.execute("SELECT nom FROM aire_sante WHERE id = %s;", (centre.id_aire_sante,))
        aire_nom = cursor.fetchone()[0]
        conn.commit()
        return {
            "message": "Centre de santé créé", 
            "id": new_id, "nom": centre.nom, "type_centre": centre.type_centre, 
            "id_aire_sante": centre.id_aire_sante, "aire_nom": aire_nom
        }
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.get("/api/admin/centres")
async def get_centres_sante(zone_id: Optional[int] = None):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Filtre sur c.etat = 'ACTIF' pour masquer les centres supprimés logiquement
        if zone_id:
            cursor.execute("""
                SELECT c.id, c.nom, c.type_centre, c.id_aire_sante, a.nom as aire_nom
                FROM centre_sante c
                JOIN aire_sante a ON c.id_aire_sante = a.id
                WHERE a.id_zone_sante = %s AND c.etat = 'ACTIF'
                ORDER BY c.nom;
            """, (zone_id,))
        else:
            cursor.execute("""
                SELECT c.id, c.nom, c.type_centre, c.id_aire_sante, a.nom as aire_nom
                FROM centre_sante c
                JOIN aire_sante a ON c.id_aire_sante = a.id 
                WHERE c.etat = 'ACTIF'
                ORDER BY c.nom;
            """)
        return cursor.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.put("/api/admin/centres/{centre_id}")
async def modifier_centre_sante(centre_id: int, centre: CentreSanteCreate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Ne modifier que si le centre est toujours actif
        cursor.execute("""
            UPDATE centre_sante 
            SET nom = %s, type_centre = %s, id_aire_sante = %s
            WHERE id = %s AND etat = 'ACTIF';
        """, (centre.nom, centre.type_centre, centre.id_aire_sante, centre_id))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Centre introuvable ou inactif.")
            
        cursor.execute("SELECT nom FROM aire_sante WHERE id = %s;", (centre.id_aire_sante,))
        aire_nom = cursor.fetchone()[0]
        conn.commit()
        
        return {
            "message": "Centre de santé mis à jour", 
            "id": centre_id, "nom": centre.nom, "type_centre": centre.type_centre, 
            "id_aire_sante": centre.id_aire_sante, "aire_nom": aire_nom
        }
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.delete("/api/admin/centres/{centre_id}")
async def supprimer_centre_sante(centre_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # LOGIQUE MÉTIER : Y a-t-il des cas dans ce centre ?
        cursor.execute("SELECT COUNT(*) FROM cas_maladie WHERE id_centre_sante = %s;", (centre_id,))
        nb_cas = cursor.fetchone()[0]

        if nb_cas > 0:
            # S'il a des cas, on ne le supprime pas, on le désactive pour protéger l'historique !
            cursor.execute("UPDATE centre_sante SET etat = 'INACTIF' WHERE id = %s;", (centre_id,))
            message = f"Le centre a été désactivé (INACTIF) car il contient {nb_cas} cas d'épidémie."
        else:
            # S'il n'y a pas de cas, on vérifie d'abord qu'aucun médecin actif n'y est affecté
            try:
                cursor.execute("DELETE FROM centre_sante WHERE id = %s AND etat = 'ACTIF';", (centre_id,))
                if cursor.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Centre introuvable ou déjà inactif.")
                message = "Centre de santé supprimé définitivement."
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()
                cursor = conn.cursor()
                # Un médecin y est rattaché, on se rabat sur la désactivation
                cursor.execute("UPDATE centre_sante SET etat = 'INACTIF' WHERE id = %s;", (centre_id,))
                message = "Le centre a été désactivé (Des médecins y sont affectés)."

        conn.commit()
        return {"message": message}
    except HTTPException as he:
        raise he
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
# ==========================================
# ROUTES : UTILISATEURS (COMPTES)
class UtilisateurCreate(BaseModel):
    id: Optional[int] = None
    nom: Optional[str] = None      #  Devient optionnel
    login: str
    mdp: str
    role: str
    id_centre: Optional[int] = None #  Devient optionnel (accepte None/null pour le MCZ)
    sexe: str = 'M'
    telephone: str = ''
@app.post("/api/admin/utilisateurs")
async def creer_utilisateur(user: UtilisateurCreate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Détermination de l'ID du rôle
        if user.role == 'MCZ': 
            id_role = 1
        elif user.role == 'MEDECIN': 
            id_role = 2
        else: 
            id_role = 3
            
        cursor.execute("""
            INSERT INTO utilisateur (nom_utilisateur, mot_de_passe, etat, id_role, sexe, telephone,id_centre_sante)
            VALUES (%s, %s, 'ACTIF', %s, %s, %s,%s) RETURNING id;
        """, (user.login, user.mdp, id_role, user.sexe, user.telephone,user.id_centre))
        
        new_id = cursor.fetchone()[0]
        conn.commit()
        return {"message": "Utilisateur créé", "id": new_id}
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
@app.put("/api/admin/utilisateurs/{user_id}")
async def modifier_utilisateur(user_id: int, user: UtilisateurCreate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Détermination du rôle et gestion du centre
        if user.role == 'MCZ': 
            id_role = 1
            # Le MCZ n'appartient à aucun centre, on force NULL
            user.id_centre = None
        elif user.role == 'MEDECIN': 
            id_role = 2
        else: 
            id_role = 3
        
        # Si le mdp n'est PAS vide, on met à TOUT jour y compris le mot de passe
        if user.mdp and user.mdp.strip() != '':
            cursor.execute("""
                UPDATE utilisateur 
                SET nom_utilisateur = %s, mot_de_passe = %s, id_role = %s, sexe = %s, telephone = %s, id_centre_sante = %s
                WHERE id = %s;
            """, (user.login, user.mdp, id_role, user.sexe, user.telephone, user.id_centre, user_id))
        else:
            # Sinon, on met à jour le reste sans toucher au mot de passe actuel
            cursor.execute("""
                UPDATE utilisateur 
                SET nom_utilisateur = %s, id_role = %s, sexe = %s, telephone = %s, id_centre_sante = %s
                WHERE id = %s;
            """, (user.login, id_role, user.sexe, user.telephone, user.id_centre, user_id))
            
        conn.commit()
        return {"message": "Utilisateur mis à jour !"}
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
        
@app.get("/api/admin/utilisateurs")
async def get_utilisateurs():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # ✅ FILTRE : On ne remonte que les Utilisateurs ACTIFS 
        # (les médecins / infirmiers désactivés n'apparaîtront plus ici)
        cursor.execute("""
            SELECT u.id, u.nom_utilisateur as login, r.nom as role, 
                   COALESCE(c.nom, 'Zone Globale') as centre,
                   u.sexe, u.telephone
            FROM utilisateur u
            JOIN role_utilisateur r ON u.id_role = r.id
            LEFT JOIN centre_sante c ON u.id_centre_sante = c.id
            WHERE r.nom IN ('MCZ', 'MEDECIN', 'INFIRMIER') AND u.etat = 'ACTIF'
            ORDER BY u.id DESC;
        """)
        return cursor.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

@app.delete("/api/admin/utilisateurs/{user_id}")
async def supprimer_utilisateur(user_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # On vérifie d'abord si le médecin a déjà créé des cas
        cursor.execute("SELECT COUNT(*) FROM cas_maladie WHERE id_utilisateur = %s;", (user_id,))
        nb_cas = cursor.fetchone()[0]

        if nb_cas > 0:
            # S'il a des cas, on ne peut pas le supprimer, on le désactive (INACTIF)
            cursor.execute("UPDATE utilisateur SET etat = 'INACTIF' WHERE id = %s;", (user_id,))
            message = f"Ce compte a enregistré {nb_cas} cas. Il a été désactivé (INACTIF) au lieu d'être supprimé."
        else:
            # S'il n'a rien fait, on peut le supprimer physiquement
            cursor.execute("DELETE FROM utilisateur WHERE id = %s;", (user_id,))
            message = "Compte médical supprimé avec succès."
            
        conn.commit()
        return {"message": message}
    except Exception as e:
        if 'conn' in locals(): conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

# ==========================================
# ROUTES : SAISIE DES CAS (MANUELLE & OCR)
# ==========================================
class CasMaladieCreate(BaseModel):
    patientNom: str
    patientPrenom: str
    patientPostnom: Optional[str] = ""
    dateNaissance: Optional[str] = None
    sexe: str = 'M'
    telephone: Optional[str] = ""
    commune: str
    quartier: str = ""
    avenue: str = ""
    numeroResidence: str = ""
    symptomes: str = ''
    statutId: int = 1
    sourceSaisie: str
    lat_gps: Optional[float] = None
    lng_gps: Optional[float] = None
    id_centre: int
    id_utilisateur: int

@app.post("/api/cas")
async def creer_nouveau_cas(cas_data: CasMaladieCreate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # ==============================================================
        # 🌍 GÉOCODAGE INTELLIGENT (Avec Jitter Mathématique)
        # ==============================================================
        coords = geocode.obtenir_coordonnees(
            avenue=cas_data.avenue, 
            quartier=cas_data.quartier, 
            commune=cas_data.commune,
            lat_gps=cas_data.lat_gps,
            lng_gps=cas_data.lng_gps
        )

        cursor.execute("""
            INSERT INTO adresse (commune, quartier, avenue, numero, latitude, longitude, niveau_precision)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;
        """, (
            cas_data.commune, 
            cas_data.quartier, 
            cas_data.avenue, 
            cas_data.numeroResidence, 
            coords["lat"], 
            coords["lng"],
            coords["precision"]
        ))
        id_adresse = cursor.fetchone()[0]

        # -------------------------------------------------------------
        # SUITE NORMALE DE L'ENREGISTREMENT
        # -------------------------------------------------------------
        cursor.execute("""
            INSERT INTO patient (nom, prenom, post_nom, sexe, telephone, date_insertion, id_adresse)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s) RETURNING id;
        """, (cas_data.patientNom, cas_data.patientPrenom, cas_data.patientPostnom, cas_data.sexe, cas_data.telephone, id_adresse))
        id_patient = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO cas_maladie (id_patient, id_maladie, id_centre_sante, id_adresse, id_utilisateur, id_statut)
            VALUES (%s, 1, %s, %s, %s, %s) RETURNING id;
        """, (id_patient, cas_data.id_centre, id_adresse, cas_data.id_utilisateur, cas_data.statutId))
        id_cas = cursor.fetchone()[0]

        if cas_data.symptomes:
            cursor.execute("""
                INSERT INTO symptome_cas (nom_symptome, id_cas_maladie)
                VALUES (%s, %s);
            """, (cas_data.symptomes, id_cas))

        conn.commit()
        return {
            "message": "Cas enregistré avec succès !", 
            "cas_id": id_cas,
            "geo_precision": coords["precision"]
        }

    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
        
# ==========================================
# ROUTES : NUMÉRISATION SIMR
# ==========================================
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/api/simr/upload")
async def upload_simr_form(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        result = ocr_simr.traiter_image_simr(file_path)
        return {"message": "Fiche scannée", "image_url": file_path, "ocr_data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur OCR : {str(e)}")

@app.post("/api/admin/run-dbscan")
async def trigger_dbscan():
    try:
        tache_planifiee_dbscan()
        return {"message": "DBSCAN exécuté avec succès."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
