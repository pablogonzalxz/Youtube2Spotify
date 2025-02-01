from django.shortcuts import render
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import time
from dotenv import load_dotenv
import os
import re
from spotipy.oauth2 import SpotifyOAuth
import spotipy
import webbrowser
import json
import validators
import requests
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt

def home(request):
    return render(request, 'global/home.html')

load_dotenv()

# Acesse as variáveis de ambiente
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

SCOPE = "playlist-modify-public playlist-modify-private"

sp_oauth = SpotifyOAuth(client_id=CLIENT_ID,
                         client_secret=CLIENT_SECRET,
                         redirect_uri=REDIRECT_URI,
                         scope=SCOPE)

@csrf_exempt
def get_video(request):
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            url = body.get("url")

            if not url:
                return JsonResponse({"success": False, "error": "URL não fornecida."}, status=400)
            if not validators.url(url):
                return JsonResponse({"success": False, "error": "URL fornecida é inválida."}, status=400)
            if "&list=" in url:
                result, video_title = get_music_list(url)
            else:
                result, video_title = get_video_chapters_with_selenium(url)

            if not result:
                return JsonResponse({"success": False, "error": "Nenhum capítulo encontrado ou erro no processamento."}, status=500)

            playlist_url, playlist_cover_url = create_spotify_playlist_with_tracks(result, video_title)
            print(f"playlist url:{playlist_url}")
            print(f"img {playlist_cover_url}")

            return JsonResponse({
                "success": True,
                "playlist_url": playlist_url,
                "playlist_cover_url": playlist_cover_url
            }, status=200)

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse({"success": False, "error": "Método não permitido."}, status=405)

def get_music_list(url):
    service = Service("site_project/bin/chromedriver.exe")
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")  
    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get(url)
        time.sleep(8) 

        video_title = driver.find_element(By.CSS_SELECTOR, 'a.style-scope.yt-formatted-string').text.strip()
        music_list = []
        scrollable_div = driver.find_element(By.CSS_SELECTOR, '#items')

        last_height = 0

        while True:

            music_elements = driver.find_elements(By.CSS_SELECTOR, 'span#video-title.style-scope.ytd-playlist-panel-video-renderer')

            for music in music_elements:
                text = music.text.strip()
                if text and text not in [m[0] for m in music_list]:
                    clean_text = re.sub(r'\s?(\d+\.)|\s?part\.\s.*?|\s?feat\.\s.*?|\(.*?\)|[,-]', ' ', text)
                    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                    music_list.append((clean_text, ""))

            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", scrollable_div)
            time.sleep(2)

            new_height = driver.execute_script("return arguments[0].scrollHeight;", scrollable_div)
            if new_height == last_height:
                break 
            last_height = new_height

        if music_list:
            print(f"Total de músicas encontradas: {len(music_list)}")
            try:
                print(music_list)
                playlist_url, playlist_cover_url = create_spotify_playlist_with_tracks(music_list, video_title)
                print(f"Playlist criada: {playlist_url}")
            except Exception as e:
                print(f"Erro ao enviar para o Spotify: {e}")
                raise e
            return music_list, video_title


    except Exception as e:
        print(f"Erro ao buscar músicas da playlist: {e}")
        return [], ""

    finally:
        driver.quit()



def get_video_chapters_with_selenium(url):
    service = Service("site_project/bin/chromedriverwindows.exe")
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")  
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--headless")  

    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get(url)
        time.sleep(20)
        video_title = driver.find_element(By.CSS_SELECTOR, 'h1.style-scope.ytd-watch-metadata').text.strip()

        try:
            expand_button = driver.find_element(By.CSS_SELECTOR, "#description-inline-expander")
            expand_button.click()
            print("Botão de expandir clicado com sucesso.")
        except Exception as e:
            print(f"Erro ao clicar no botão de expandir: {e}")

        time.sleep(5)

        chapters_elements = driver.find_elements(By.CSS_SELECTOR, "ytd-text-inline-expander")
        chapters = [chapter.text.strip() for chapter in chapters_elements if chapter.text.strip()]

        processed_chapters = []
        for chapter_text in chapters:
            pattern = r'(\d{2}:\d{2}:\d{2})\s+(.*?)(?=\s+\d{2}:\d{2}:\d{2}|$)'
            matches = re.finditer(pattern, chapter_text)

            for match in matches:
                timestamp = match.group(1)
                title_artist = match.group(2).strip()

                if " by " in title_artist:
                    title, artist = title_artist.split(" by ", 1)
                    title = title.strip()
                    artist = artist.strip()
                else:
                    title = title_artist
                    artist = ""

                processed_chapters.append((title, artist))

        if processed_chapters:
            print(f"Capítulos encontrados: {processed_chapters}")
            try:
                create_spotify_playlist_with_tracks(processed_chapters, video_title)
            except Exception as e:
                print(f"Erro ao enviar para o Spotify: {e}")
                raise e

            return processed_chapters, video_title

        # Caso a primeira tentativa tenha falhado, tenta buscar em outro elemento
        titles = driver.find_elements(By.CSS_SELECTOR, ".yt-video-attribute-view-model__title")
        artists = driver.find_elements(By.CSS_SELECTOR, ".yt-video-attribute-view-model__subtitle")
        
        for i in range(min(len(titles), len(artists))):
            title = titles[i].text.strip()
            artist = artists[i].text.strip() if i < len(artists) else ""

            if title:
                if artist:
                    processed_chapters.append((title, artist))
                else:
                    processed_chapters.append((title, ""))

        processed_titles = set()

        while True:
            try:
                try:
                    element = driver.find_element(By.CSS_SELECTOR, '#right-arrow yt-icon[icon="yt-icons:chevron_right"]')
                    driver.execute_script("arguments[0].click();", element)
                except Exception as e:
                    print(f"Erro ao tentar clicar no botão de expandir: {e}")

                WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'h4.macro-markers.style-scope.ytd-macro-markers-list-item-renderer'))
                )

                titles = driver.find_elements(By.CSS_SELECTOR, 'h4.macro-markers.style-scope.ytd-macro-markers-list-item-renderer')

                for title_element in titles:
                    title = title_element.get_attribute("title").strip()

                    if not title:
                        print(f"Título vazio encontrado, ignorando...")
                        continue 

                    if title in processed_titles:
                        print(f"Primeiro título encontrado novamente: {title}. Interrompendo o loop.")
                        raise StopIteration  

                    processed_titles.add(title)
                    processed_chapters.append((title, artist))
                    print(f"Capítulo encontrado: {title}")

            except StopIteration:
                break
            except Exception as e:
                print(f"Erro ao tentar clicar no botão de expandir ou buscar capítulos: {e}")
                break  

        return processed_chapters, video_title 

    except Exception as e:
        print(f"Erro ao buscar capítulos: {e}")
        return [], "" 

    finally:
        driver.quit()


def index(request):
    token_info = sp_oauth.get_cached_token()
    print(f"Token Info: {token_info}")
    if token_info:
        access_token = token_info['access_token']
        sp = spotipy.Spotify(auth=access_token)
        user_data = sp.current_user()
        user_name = user_data['display_name'] if user_data['display_name'] else user_data['id']
        return HttpResponse(f"Usuário autenticado: {user_name}")
    else:
        auth_url = sp_oauth.get_authorize_url()
        webbrowser.open(auth_url) 
        return HttpResponse("Por favor, autorize a aplicação no navegador e depois volte aqui.")

def callback():
    code = requests.GET.get('code')

    if code:
        token_info = sp_oauth.get_access_token(code)

        sp = spotipy.Spotify(auth=token_info['access_token'])
        user_id = sp.current_user()['id']
        return f"Usuário autenticado: {user_id}"
    else:
        return "Código de autorização não fornecido."

def create_spotify_playlist_with_tracks(musicas, video_title):
    token_info = sp_oauth.get_cached_token()
    if not token_info:
        raise Exception("Usuário não autenticado. Acesse o URL e forneça o código de autorização.")

    sp = spotipy.Spotify(auth=token_info['access_token'])
    user_id = sp.current_user()['id']
    playlist_name = video_title

    playlist = sp.user_playlist_create(user_id, playlist_name, public=True)
    playlist_id = playlist['id']
    playlist_url = playlist['external_urls']['spotify'] 
    print(f"Playlist criada com ID: {playlist_id} e URL: {playlist_url}")

    musicas_with_artist = [(musica, artista) for musica, artista in musicas if artista]
    musicas_no_artist = [musica for musica, artista in musicas if not artista]

    track_ids = []
    for musica, artista in musicas_with_artist:
        query = f"{musica} {artista}"
        result = sp.search(query, limit=1, type='track', market='US')
        
        if result['tracks']['items']:
            track_id = result['tracks']['items'][0]['id']
            track_ids.append(track_id)
        else:
            print(f"Música '{musica}' de {artista} não encontrada no Spotify.")

    for musica in musicas_no_artist:
        query = musica
        result = sp.search(query, limit=1, type='track', market='US')
        
        if result['tracks']['items']:
            track_id = result['tracks']['items'][0]['id']
            track_ids.append(track_id)
        else:
            print(f"Música '{musica}' não encontrada no Spotify.")

    if track_ids:
        sp.playlist_add_items(playlist_id, track_ids)
        print(f"Músicas adicionadas à playlist: {'/n '.join([musica for musica, _ in musicas])}")
    else:
        print("Nenhuma música foi adicionada à playlist.")

    playlist_details = sp.playlist(playlist_id)
    playlist_image = playlist_details['images'][0]['url'] if playlist_details['images'] else None

    return playlist_url, playlist_image
