import os
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

async def fetch_game(session: aiohttp.ClientSession, query: str) -> dict | None:
    params = {"key": RAWG_API_KEY, "search": query, "page_size": 1}
    async with session.get(f"{RAWG_BASE}/games", params=params) as r:
        if r.status != 200:
            return None
        data = await r.json()
        results = data.get("results", [])
        if not results:
            return None
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

async def fetch_movie(session: aiohttp.ClientSession, query: str) -> dict | None:
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "fr-FR"}
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
        return await r.json()


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

    if genres:
        embed.add_field(name="Genres", value=genres, inline=True)
    if homepage:
        embed.add_field(name="Site officiel", value=f"[Lien]({homepage})", inline=True)
    if imdb_id:
        embed.add_field(name="IMDb", value=f"[Lien](https://www.imdb.com/title/{imdb_id})", inline=True)

    embed.set_footer(text="Source : TMDB")
    return embed


# --- TMDB (séries) ---

async def fetch_show(session: aiohttp.ClientSession, query: str) -> dict | None:
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "fr-FR"}
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
        return await r.json()


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

    if genres:
        embed.add_field(name="Genres", value=genres, inline=True)
    embed.add_field(name="Saisons", value=str(seasons), inline=True)
    embed.add_field(name="Statut", value=status, inline=True)

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
)
@app_commands.choices(type=[
    app_commands.Choice(name="🎮 Jeu vidéo", value="game"),
    app_commands.Choice(name="🎬 Film", value="movie"),
    app_commands.Choice(name="📺 Série", value="show"),
])
async def score(interaction: discord.Interaction, type: app_commands.Choice[str], titre: str):
    await interaction.response.defer()

    async with aiohttp.ClientSession() as session:
        if type.value == "game":
            data = await fetch_game(session, titre)
            if not data:
                await interaction.followup.send(f"❌ Aucun jeu trouvé pour **{titre}**.")
                return
            embed = build_game_embed(data)

        elif type.value == "movie":
            data = await fetch_movie(session, titre)
            if not data:
                await interaction.followup.send(f"❌ Aucun film trouvé pour **{titre}**.")
                return
            embed = build_movie_embed(data)

        else:
            data = await fetch_show(session, titre)
            if not data:
                await interaction.followup.send(f"❌ Aucune série trouvée pour **{titre}**.")
                return
            embed = build_show_embed(data)

    await interaction.followup.send(embed=embed)


@client.event
async def on_ready():
    print(f"✅ Connecté en tant que {client.user} (ID: {client.user.id})")
    print("Slash commands synchronisées.")


client.run(DISCORD_TOKEN)
