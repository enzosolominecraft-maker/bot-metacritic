import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
RAWG_API_KEY = os.getenv("RAWG_API_KEY")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

RAWG_BASE = "https://api.rawg.io/api"
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w500"

# --- Score color helper ---

def score_color(score: int | None) -> discord.Color:
    if score is None:
        return discord.Color.light_grey()
    if score >= 75:
        return discord.Color.green()
    if score >= 50:
        return discord.Color.yellow()
    return discord.Color.red()


def score_emoji(score: int | None) -> str:
    if score is None:
        return "⬜"
    if score >= 75:
        return "🟢"
    if score >= 50:
        return "🟡"
    return "🔴"


# --- RAWG (jeux) ---

async def fetch_game(session: aiohttp.ClientSession, query: str, year: int | None = None) -> dict | None:
    params = {"key": RAWG_API_KEY, "search": query, "page_size": 10}
    async with session.get(f"{RAWG_BASE}/games", params=params) as r:
        if r.status != 200:
            return None
        data = await r.json()
        results = data.get("results", [])
        if not results:
            return None
        if year:
            match = next((g for g in results if (g.get("released") or "").startswith(str(year))), None)
            game = match or results[0]
        else:
            game = results[0]

    # Détail complet pour avoir metacritic + description
    async with session.get(f"{RAWG_BASE}/games/{game['id']}", params={"key": RAWG_API_KEY}) as r:
        if r.status != 200:
            return None
        return await r.json()


def build_game_embed(data: dict) -> discord.Embed:
    name = data.get("name", "Inconnu")
    released = (data.get("released") or "?")[:4]
    metacritic = data.get("metacritic")
    platforms = ", ".join(p["platform"]["name"] for p in (data.get("platforms") or [])[:3])
    genres = ", ".join(g["name"] for g in (data.get("genres") or [])[:3])
    website = data.get("website") or ""
    bg_image = data.get("background_image") or ""

    embed = discord.Embed(
        title=f"🎮 {name} ({released})",
        color=score_color(metacritic),
        url=f"https://www.metacritic.com/search/{name.replace(' ', '%20')}",
    )

    if bg_image:
        embed.set_thumbnail(url=bg_image)

    score_text = f"{score_emoji(metacritic)} **{metacritic}/100**" if metacritic else "Non disponible"
    embed.add_field(name="Metacritic (presse)", value=score_text, inline=False)

    if genres:
        embed.add_field(name="Genres", value=genres, inline=True)
    if platforms:
        embed.add_field(name="Plateformes", value=platforms, inline=True)
    if website:
        embed.add_field(name="Site officiel", value=f"[Lien]({website})", inline=True)

    embed.set_footer(text="Source : RAWG.io")
    return embed


# --- TMDB (films) ---

async def fetch_movie(session: aiohttp.ClientSession, query: str, year: int | None = None) -> dict | None:
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "fr-FR"}
    if year:
        params["primary_release_year"] = year
    async with session.get(f"{TMDB_BASE}/search/movie", params=params) as r:
        if r.status != 200:
            return None
        data = await r.json()
        results = data.get("results", [])
        if not results:
            return None
        movie_id = results[0]["id"]

    params = {"api_key": TMDB_API_KEY, "language": "fr-FR"}
    async with session.get(f"{TMDB_BASE}/movie/{movie_id}", params=params) as r:
        if r.status != 200:
            return None
        detail = await r.json()

    async with session.get(f"{TMDB_BASE}/movie/{movie_id}/credits", params=params) as r:
        credits = await r.json() if r.status == 200 else {}

    crew = credits.get("crew", [])
    detail["_directors"] = [p["name"] for p in crew if p.get("job") == "Director"]
    detail["_writers"] = [p["name"] for p in crew if p.get("job") in ("Writer", "Screenplay", "Story")]
    return detail


def build_movie_embed(data: dict) -> discord.Embed:
    title = data.get("title", "Inconnu")
    year = (data.get("release_date") or "?")[:4]
    metacritic = data.get("vote_average")  # TMDB n'a pas Metacritic direct
    mc_score = round(metacritic * 10) if metacritic else None
    genres = ", ".join(g["name"] for g in (data.get("genres") or [])[:3])
    poster = f"{TMDB_IMG_BASE}{data['poster_path']}" if data.get("poster_path") else ""
    homepage = data.get("homepage") or ""
    imdb_id = data.get("imdb_id") or ""

    embed = discord.Embed(
        title=f"🎬 {title} ({year})",
        color=score_color(mc_score),
        url=f"https://www.metacritic.com/search/{title.replace(' ', '%20')}",
    )

    if poster:
        embed.set_thumbnail(url=poster)

    # TMDB ne fournit pas le score Metacritic — on affiche le score TMDB
    score_text = f"{score_emoji(mc_score)} **{metacritic:.1f}/10** (TMDB)" if metacritic else "Non disponible"
    embed.add_field(name="Note (presse / TMDB)", value=score_text, inline=False)

    note = (
        "⚠️ TMDB ne fournit pas le score Metacritic officiel.\n"
        "Le score affiché est la note agrégée TMDB."
    )
    embed.add_field(name="ℹ️ Note", value=note, inline=False)

    directors = ", ".join(data.get("_directors", [])[:2])
    writers = ", ".join(data.get("_writers", [])[:2])

    if genres:
        embed.add_field(name="Genres", value=genres, inline=True)
    if directors:
        embed.add_field(name="Réalisateur(s)", value=directors, inline=True)
    if writers:
        embed.add_field(name="Scénariste(s)", value=writers, inline=True)
    if homepage:
        embed.add_field(name="Site officiel", value=f"[Lien]({homepage})", inline=True)
    if imdb_id:
        embed.add_field(name="IMDb", value=f"[Lien](https://www.imdb.com/title/{imdb_id})", inline=True)

    embed.set_footer(text="Source : TMDB")
    return embed


# --- TMDB (séries) ---

async def fetch_show(session: aiohttp.ClientSession, query: str, year: int | None = None) -> dict | None:
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "fr-FR"}
    if year:
        params["first_air_date_year"] = year
    async with session.get(f"{TMDB_BASE}/search/tv", params=params) as r:
        if r.status != 200:
            return None
        data = await r.json()
        results = data.get("results", [])
        if not results:
            return None
        show_id = results[0]["id"]

    params = {"api_key": TMDB_API_KEY, "language": "fr-FR"}
    async with session.get(f"{TMDB_BASE}/tv/{show_id}", params=params) as r:
        if r.status != 200:
            return None
        detail = await r.json()

    async with session.get(f"{TMDB_BASE}/tv/{show_id}/credits", params=params) as r:
        credits = await r.json() if r.status == 200 else {}

    crew = credits.get("crew", [])
    detail["_writers"] = [p["name"] for p in crew if p.get("job") in ("Writer", "Screenplay", "Story")]
    return detail


def build_show_embed(data: dict) -> discord.Embed:
    name = data.get("name", "Inconnu")
    year = (data.get("first_air_date") or "?")[:4]
    vote = data.get("vote_average")
    score = round(vote * 10) if vote else None
    genres = ", ".join(g["name"] for g in (data.get("genres") or [])[:3])
    poster = f"{TMDB_IMG_BASE}{data['poster_path']}" if data.get("poster_path") else ""
    seasons = data.get("number_of_seasons", "?")
    status = data.get("status", "?")

    embed = discord.Embed(
        title=f"📺 {name} ({year})",
        color=score_color(score),
        url=f"https://www.metacritic.com/search/{name.replace(' ', '%20')}",
    )

    if poster:
        embed.set_thumbnail(url=poster)

    score_text = f"{score_emoji(score)} **{vote:.1f}/10** (TMDB)" if vote else "Non disponible"
    embed.add_field(name="Note (presse / TMDB)", value=score_text, inline=False)

    note = (
        "⚠️ TMDB ne fournit pas le score Metacritic officiel.\n"
        "Le score affiché est la note agrégée TMDB."
    )
    embed.add_field(name="ℹ️ Note", value=note, inline=False)

    creators = ", ".join(c["name"] for c in (data.get("created_by") or [])[:2])
    writers = ", ".join(data.get("_writers", [])[:2])

    if genres:
        embed.add_field(name="Genres", value=genres, inline=True)
    embed.add_field(name="Saisons", value=str(seasons), inline=True)
    embed.add_field(name="Statut", value=status, inline=True)
    if creators:
        embed.add_field(name="Créateur(s)", value=creators, inline=True)
    if writers:
        embed.add_field(name="Scénariste(s)", value=writers, inline=True)

    embed.set_footer(text="Source : TMDB")
    return embed


# --- Bot setup ---

class MetacriticBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


client = MetacriticBot()

MediaType = app_commands.Choice


@client.tree.command(name="score", description="Affiche la note Metacritic (presse) d'un jeu, film ou série")
@app_commands.describe(
    type="Type de média",
    titre="Titre à rechercher",
    annee="Année de sortie (optionnel, pour départager deux titres identiques)",
)
@app_commands.choices(type=[
    app_commands.Choice(name="🎮 Jeu vidéo", value="game"),
    app_commands.Choice(name="🎬 Film", value="movie"),
    app_commands.Choice(name="📺 Série", value="show"),
])
async def score(interaction: discord.Interaction, type: app_commands.Choice[str], titre: str, annee: int = None):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        if type.value == "game":
            data = await fetch_game(session, titre, annee)
            if not data:
                await interaction.followup.send(f"❌ Aucun jeu trouvé pour **{titre}**.")
                return
            embed = build_game_embed(data)

        elif type.value == "movie":
            data = await fetch_movie(session, titre, annee)
            if not data:
                await interaction.followup.send(f"❌ Aucun film trouvé pour **{titre}**.")
                return
            embed = build_movie_embed(data)

        else:
            data = await fetch_show(session, titre, annee)
            if not data:
                await interaction.followup.send(f"❌ Aucune série trouvée pour **{titre}**.")
                return
            embed = build_show_embed(data)

    await interaction.followup.send(embed=embed)


# --- TMDB (réalisateur) ---

async def fetch_director(session: aiohttp.ClientSession, query: str) -> dict | None:
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "fr-FR"}
    async with session.get(f"{TMDB_BASE}/search/person", params=params) as r:
        if r.status != 200:
            return None
        data = await r.json()
        results = data.get("results", [])
        if not results:
            return None
        person_id = results[0]["id"]

    params = {"api_key": TMDB_API_KEY, "language": "fr-FR"}
    async with session.get(f"{TMDB_BASE}/person/{person_id}", params=params) as r:
        if r.status != 200:
            return None
        detail = await r.json()

    # Films en tant que réalisateur
    async with session.get(f"{TMDB_BASE}/person/{person_id}/movie_credits", params=params) as r:
        credits = await r.json() if r.status == 200 else {}

    directed = [
        m for m in credits.get("crew", [])
        if m.get("job") == "Director" and m.get("release_date")
    ]
    directed.sort(key=lambda m: m.get("release_date", ""), reverse=True)
    detail["_directed"] = directed
    return detail


def build_director_embed(data: dict) -> discord.Embed:
    name = data.get("name", "Inconnu")
    birthday = data.get("birthday") or "?"
    deathday = data.get("deathday")
    birthplace = data.get("place_of_birth") or "?"
    biography = data.get("biography") or ""
    photo = f"{TMDB_IMG_BASE}{data['profile_path']}" if data.get("profile_path") else ""
    tmdb_url = f"https://www.themoviedb.org/person/{data.get('id')}"

    # Âge ou années de vie
    if deathday:
        age_str = f"{birthday} – {deathday}"
    elif birthday and birthday != "?":
        from datetime import date
        try:
            birth_year = int(birthday[:4])
            age = date.today().year - birth_year
            age_str = f"{birthday} ({age} ans)"
        except ValueError:
            age_str = birthday
    else:
        age_str = birthday

    embed = discord.Embed(
        title=f"🎬 {name}",
        color=discord.Color.blurple(),
        url=tmdb_url,
    )

    if photo:
        embed.set_thumbnail(url=photo)

    embed.add_field(name="Naissance", value=age_str, inline=True)
    embed.add_field(name="Lieu de naissance", value=birthplace, inline=True)

    # Filmographie (5 films les plus récents)
    directed = data.get("_directed", [])
    if directed:
        films = "\n".join(
            f"• **{m['title']}** ({m.get('release_date', '')[:4]})"
            for m in directed[:5]
        )
        total = len(directed)
        embed.add_field(
            name=f"Filmographie ({total} films)",
            value=films,
            inline=False,
        )

    # Biographie (tronquée à 300 caractères)
    if biography:
        short_bio = biography[:300] + "…" if len(biography) > 300 else biography
        embed.add_field(name="Biographie", value=short_bio, inline=False)

    embed.set_footer(text="Source : TMDB")
    return embed


@client.tree.command(name="realisateur", description="Affiche la fiche TMDB d'un réalisateur")
@app_commands.describe(nom="Nom du réalisateur")
async def realisateur(interaction: discord.Interaction, nom: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        data = await fetch_director(session, nom)
        if not data:
            await interaction.followup.send(f"❌ Aucun réalisateur trouvé pour **{nom}**.")
            return
        embed = build_director_embed(data)

    await interaction.followup.send(embed=embed)


# --- RAWG (créateur de jeux) ---

async def fetch_game_creator(session: aiohttp.ClientSession, query: str) -> dict | None:
    # Recherche du créateur
    params = {"key": RAWG_API_KEY, "search": query, "page_size": 5}
    async with session.get(f"{RAWG_BASE}/creators", params=params) as r:
        if r.status != 200:
            return None
        data = await r.json()
        results = data.get("results", [])
        if not results:
            return None
        creator = results[0]
        creator_id = creator["id"]

    # Détail du créateur
    async with session.get(f"{RAWG_BASE}/creators/{creator_id}", params={"key": RAWG_API_KEY}) as r:
        if r.status != 200:
            return None
        detail = await r.json()

    # Jeux du créateur (jusqu'à 40 pour avoir assez de données)
    params = {"key": RAWG_API_KEY, "creators": creator_id, "page_size": 40}
    async with session.get(f"{RAWG_BASE}/games", params=params) as r:
        if r.status != 200:
            return detail
        games_data = await r.json()
        games = games_data.get("results", [])

    # Top 10 par note Metacritic
    with_score = [g for g in games if g.get("metacritic")]
    top_rated = sorted(with_score, key=lambda g: g["metacritic"], reverse=True)[:10]

    # 10 plus récents (par date de sortie)
    with_date = [g for g in games if g.get("released")]
    most_recent = sorted(with_date, key=lambda g: g["released"], reverse=True)[:10]

    detail["_top_rated"] = top_rated
    detail["_most_recent"] = most_recent
    return detail


def build_game_creator_embed(data: dict) -> discord.Embed:
    name = data.get("name", "Inconnu")
    image = data.get("image") or data.get("image_background") or ""
    games_count = data.get("games_count", 0)
    description = data.get("description") or ""
    positions = ", ".join(p["name"] for p in (data.get("positions") or [])[:3])
    tmdb_url = f"https://rawg.io/creators/{data.get('slug', '')}"

    embed = discord.Embed(
        title=f"🕹️ {name}",
        color=discord.Color.og_blurple(),
        url=tmdb_url,
    )

    if image:
        embed.set_thumbnail(url=image)

    if positions:
        embed.add_field(name="Rôle(s)", value=positions, inline=True)
    embed.add_field(name="Jeux au total", value=str(games_count), inline=True)

    # Top 10 jeux les mieux notés
    top_rated = data.get("_top_rated", [])
    if top_rated:
        lines = "\n".join(
            f"`{g['metacritic']:>3}/100` • **{g['name']}** ({(g.get('released') or '')[:4]})"
            for g in top_rated
        )
        embed.add_field(name="🏆 Top 10 mieux notés (Metacritic)", value=lines, inline=False)

    # 10 jeux les plus récents
    most_recent = data.get("_most_recent", [])
    if most_recent:
        lines = "\n".join(
            f"• **{g['name']}** ({(g.get('released') or '')[:4]})"
            + (f" — `{g['metacritic']}/100`" if g.get("metacritic") else "")
            for g in most_recent
        )
        embed.add_field(name="🕐 10 jeux les plus récents", value=lines, inline=False)

    # Biographie courte
    if description:
        import re
        clean = re.sub(r"<[^>]+>", "", description)  # retire le HTML
        short = clean[:300] + "…" if len(clean) > 300 else clean
        embed.add_field(name="Biographie", value=short, inline=False)

    embed.set_footer(text="Source : RAWG.io")
    return embed


@client.tree.command(name="createur", description="Affiche la fiche d'un créateur de jeux vidéo")
@app_commands.describe(nom="Nom du créateur (ex: Shigeru Miyamoto, Hideo Kojima)")
async def createur(interaction: discord.Interaction, nom: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        data = await fetch_game_creator(session, nom)
        if not data:
            await interaction.followup.send(f"❌ Aucun créateur trouvé pour **{nom}**.")
            return
        embed = build_game_creator_embed(data)

    await interaction.followup.send(embed=embed)


# --- RAWG (studio de jeux) ---

async def fetch_studio(session: aiohttp.ClientSession, query: str) -> dict | None:
    # Recherche du studio
    params = {"key": RAWG_API_KEY, "search": query, "page_size": 5}
    async with session.get(f"{RAWG_BASE}/developers", params=params) as r:
        if r.status != 200:
            return None
        data = await r.json()
        results = data.get("results", [])
        if not results:
            return None
        studio_id = results[0]["id"]

    # Détail du studio
    async with session.get(f"{RAWG_BASE}/developers/{studio_id}", params={"key": RAWG_API_KEY}) as r:
        if r.status != 200:
            return None
        detail = await r.json()

    # Jeux du studio (jusqu'à 40 pour avoir assez de données)
    params = {"key": RAWG_API_KEY, "developers": studio_id, "page_size": 40}
    async with session.get(f"{RAWG_BASE}/games", params=params) as r:
        if r.status != 200:
            return detail
        games_data = await r.json()
        games = games_data.get("results", [])

    # Top 10 par note Metacritic
    with_score = [g for g in games if g.get("metacritic")]
    top_rated = sorted(with_score, key=lambda g: g["metacritic"], reverse=True)[:10]

    # 10 plus récents
    with_date = [g for g in games if g.get("released")]
    most_recent = sorted(with_date, key=lambda g: g["released"], reverse=True)[:10]

    detail["_top_rated"] = top_rated
    detail["_most_recent"] = most_recent
    return detail


def build_studio_embed(data: dict) -> discord.Embed:
    import re
    name = data.get("name", "Inconnu")
    image = data.get("image") or data.get("image_background") or ""
    games_count = data.get("games_count", 0)
    description = data.get("description") or ""
    slug = data.get("slug", "")
    rawg_url = f"https://rawg.io/developers/{slug}"

    embed = discord.Embed(
        title=f"🏢 {name}",
        color=discord.Color.dark_blue(),
        url=rawg_url,
    )

    if image:
        embed.set_thumbnail(url=image)

    # Année de fondation extraite de la description (RAWG ne l'expose pas en champ dédié)
    founded_year = None
    if description:
        match = re.search(r"founded\D{0,10}(\d{4})|(\d{4})\D{0,10}founded|established\D{0,10}(\d{4})", description, re.IGNORECASE)
        if match:
            founded_year = next(y for y in match.groups() if y)

    if founded_year:
        embed.add_field(name="Fondé en", value=founded_year, inline=True)
    embed.add_field(name="Jeux au total", value=str(games_count), inline=True)

    # Top 10 jeux les mieux notés
    top_rated = data.get("_top_rated", [])
    if top_rated:
        lines = "\n".join(
            f"`{g['metacritic']:>3}/100` • **{g['name']}** ({(g.get('released') or '')[:4]})"
            for g in top_rated
        )
        embed.add_field(name="🏆 Top 10 mieux notés (Metacritic)", value=lines, inline=False)

    # 10 jeux les plus récents
    most_recent = data.get("_most_recent", [])
    if most_recent:
        lines = "\n".join(
            f"• **{g['name']}** ({(g.get('released') or '')[:4]})"
            + (f" — `{g['metacritic']}/100`" if g.get("metacritic") else "")
            for g in most_recent
        )
        embed.add_field(name="🕐 10 jeux les plus récents", value=lines, inline=False)

    # Description courte
    if description:
        clean = re.sub(r"<[^>]+>", "", description)
        short = clean[:300] + "…" if len(clean) > 300 else clean
        embed.add_field(name="À propos", value=short, inline=False)

    embed.set_footer(text="Source : RAWG.io")
    return embed


@client.tree.command(name="studio", description="Affiche la fiche d'un studio de jeux vidéo")
@app_commands.describe(nom="Nom du studio (ex: Nintendo, Ubisoft, Naughty Dog)")
async def studio(interaction: discord.Interaction, nom: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        data = await fetch_studio(session, nom)
        if not data:
            await interaction.followup.send(f"❌ Aucun studio trouvé pour **{nom}**.")
            return
        embed = build_studio_embed(data)

    await interaction.followup.send(embed=embed)


@client.event
async def on_ready():
    print(f"✅ Connecté en tant que {client.user} (ID: {client.user.id})")
    print("Slash commands synchronisées.")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass  # silence les logs HTTP


def run_health_server():
    port = int(os.getenv("PORT", 8080))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()


threading.Thread(target=run_health_server, daemon=True).start()
client.run(DISCORD_TOKEN)
