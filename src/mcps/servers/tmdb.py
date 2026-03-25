from typing import Annotated, Any, Literal

import tmdbsimple as tmdb
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from mcps.config import settings
from mcps.shared.pagination import DEFAULT_LIMIT, paginate
from mcps.shared.query import apply_query, project
from mcps.shared.schema import optimize_tool_schemas

mcp = FastMCP("TMDB")
if not tmdb.API_KEY:
    tmdb.API_KEY = settings.tmdb_api_key


class Movie(BaseModel):
    id: int
    title: str
    original_title: str = ""
    overview: str = ""
    release_date: str = ""
    popularity: float = 0.0
    vote_average: float = 0.0
    vote_count: int = 0
    adult: bool = False
    video: bool = False
    genre_ids: list[int] = []
    original_language: str = ""
    poster_path: str | None = None
    backdrop_path: str | None = None


class TvShow(BaseModel):
    id: int
    name: str
    original_name: str = ""
    overview: str = ""
    first_air_date: str = ""
    popularity: float = 0.0
    vote_average: float = 0.0
    vote_count: int = 0
    adult: bool = False
    genre_ids: list[int] = []
    original_language: str = ""
    origin_country: list[str] = []
    poster_path: str | None = None
    backdrop_path: str | None = None


class MediaItem(BaseModel):
    id: int
    media_type: str = ""
    title: str
    original_title: str = ""
    overview: str = ""
    release_date: str = ""
    popularity: float = 0.0
    vote_average: float = 0.0
    genre_ids: list[int] = []
    original_language: str = ""
    poster_path: str | None = None
    alt_titles: dict[str, str] | None = None


class Genre(BaseModel):
    id: int
    name: str


class MediaList(BaseModel):
    results: list[MediaItem] | list[dict[str, Any]]
    total: int
    offset: int
    has_more: bool


class MovieList(BaseModel):
    movies: list[Movie] | list[dict[str, Any]]
    total: int
    offset: int
    has_more: bool


class GenreList(BaseModel):
    genres: list[Genre] | list[dict[str, Any]]
    total: int
    offset: int
    has_more: bool


def _movie_to_media(m: Movie, alt_titles: dict[str, str] | None = None) -> MediaItem:
    return MediaItem(
        id=m.id,
        media_type="movie",
        title=m.title,
        original_title=m.original_title,
        overview=m.overview,
        release_date=m.release_date,
        popularity=m.popularity,
        vote_average=m.vote_average,
        genre_ids=m.genre_ids,
        original_language=m.original_language,
        poster_path=m.poster_path,
        alt_titles=alt_titles,
    )


def _tv_to_media(t: TvShow, alt_titles: dict[str, str] | None = None) -> MediaItem:
    return MediaItem(
        id=t.id,
        media_type="tv",
        title=t.name,
        original_title=t.original_name,
        overview=t.overview,
        release_date=t.first_air_date,
        popularity=t.popularity,
        vote_average=t.vote_average,
        genre_ids=t.genre_ids,
        original_language=t.original_language,
        poster_path=t.poster_path,
        alt_titles=alt_titles,
    )


def _fetch_alt_titles(media_type: str, tmdb_id: int) -> dict[str, str]:
    if media_type == "movie":
        raw = tmdb.Movies(tmdb_id).alternative_titles().get("titles", [])
    else:
        raw = tmdb.TV(tmdb_id).alternative_titles().get("results", [])
    return {e.get("iso_3166_1", ""): e.get("title", "") for e in raw}


@mcp.tool
def search_media(
    query: Annotated[str | None, Field()] = None,
    imdb_id: Annotated[str | None, Field(description="IMDB ID (tt0111161)")] = None,
    media_type: Annotated[Literal["movie", "tv"] | None, Field()] = None,
    year: Annotated[int | None, Field(description="Release year")] = None,
    filter_expr: Annotated[str | None, Field(description="CEL filter. Examples: vote_average > 7.0, media_type == 'movie'")] = None,
    search: Annotated[str | None, Field(description="Fuzzy text search across all fields (handles Cyrillic, transliteration)")] = None,
    fields: Annotated[list[str] | None, Field(description="Fields (id auto-incl.)")] = None,
    sort_by: Annotated[str | None, Field(description="Sort field, - prefix for desc")] = None,
    limit: Annotated[int, Field()] = DEFAULT_LIMIT,
    offset: Annotated[int, Field()] = 0,
) -> MediaList:
    """Search movies/TV. Fields: title, original_title, media_type, overview, release_date, vote_average, genre_ids, alt_titles"""
    if not query and not imdb_id:
        raise ValueError("Provide query or imdb_id")

    items: list[MediaItem] = []

    if imdb_id:
        result = tmdb.Find(imdb_id).info(external_source="imdb_id")
        for m in result.get("movie_results", []):
            movie = Movie.model_validate(m)
            alt = _fetch_alt_titles("movie", movie.id)
            items.append(_movie_to_media(movie, alt))
        for t in result.get("tv_results", []):
            tv = TvShow.model_validate(t)
            alt = _fetch_alt_titles("tv", tv.id)
            items.append(_tv_to_media(tv, alt))
    else:
        assert query is not None  # noqa: S101 — guard for type narrowing
        tmdb_search = tmdb.Search()
        if media_type != "tv":
            movies = tmdb_search.movie(query=query, year=year).get("results", [])
            items.extend(_movie_to_media(Movie.model_validate(m)) for m in movies)
        if media_type != "movie":
            tv_shows = tmdb_search.tv(query=query)["results"]
            items.extend(_tv_to_media(TvShow.model_validate(t)) for t in tv_shows)

    filtered = apply_query(items, filter_expr, search=search, sort_by=sort_by, limit=None)
    paginated, total, has_more = paginate(filtered, limit, offset)
    projected = project(paginated, fields)
    return MediaList(results=projected, total=total, offset=offset, has_more=has_more)


@mcp.tool
def discover_movies(
    source: Annotated[
        Literal["recommendations", "similar", "genre"], Field(description="Source: recommendations/similar (movie_id) or genre (genre_id)")
    ],
    movie_id: Annotated[int | None, Field(description="TMDB movie ID")] = None,
    genre_id: Annotated[int | None, Field(description="TMDB genre ID")] = None,
    page: Annotated[int, Field()] = 1,
    filter_expr: Annotated[str | None, Field(description="CEL filter. Examples: vote_average > 7.0, release_date > '2024'")] = None,
    search: Annotated[str | None, Field(description="Fuzzy text search across all fields (handles Cyrillic, transliteration)")] = None,
    fields: Annotated[list[str] | None, Field(description="Fields (id auto-incl.)")] = None,
    sort_by: Annotated[str | None, Field(description="Sort field, - prefix for desc")] = None,
    limit: Annotated[int, Field()] = DEFAULT_LIMIT,
    offset: Annotated[int, Field()] = 0,
) -> MovieList:
    """Discover movies by recommendations, similarity, or genre. Fields: title, overview, release_date, vote_average, genre_ids"""
    if source in ("recommendations", "similar"):
        if movie_id is None:
            raise ValueError(f"movie_id required for source={source}")
        movie = tmdb.Movies(movie_id)
        raw = movie.recommendations()["results"] if source == "recommendations" else movie.similar_movies()["results"]
    else:
        if genre_id is None:
            raise ValueError("genre_id required for source=genre")
        raw = tmdb.Discover().movie(with_genres=genre_id, page=page)["results"]

    movies = [Movie.model_validate(m) for m in raw]
    filtered = apply_query(movies, filter_expr, search=search, sort_by=sort_by, limit=None)
    paginated, total, has_more = paginate(filtered, limit, offset)
    projected = project(paginated, fields)
    return MovieList(movies=projected, total=total, offset=offset, has_more=has_more)


@mcp.tool
def list_genres(
    filter_expr: Annotated[str | None, Field(description="CEL filter. Examples: name.contains('Action')")] = None,
    search: Annotated[str | None, Field(description="Fuzzy text search across all fields (handles Cyrillic, transliteration)")] = None,
    fields: Annotated[list[str] | None, Field(description="Fields (id auto-incl.)")] = None,
    sort_by: Annotated[str | None, Field(description="Sort field, - prefix for desc")] = None,
    limit: Annotated[int, Field()] = DEFAULT_LIMIT,
) -> GenreList:
    """List movie genres. Fields: name"""
    genres_api = tmdb.Genres()
    genres = [Genre.model_validate(g) for g in genres_api.movie_list()["genres"]]
    filtered = apply_query(genres, filter_expr, search=search, sort_by=sort_by, limit=None)
    paginated, total, has_more = paginate(filtered, limit, 0)
    projected = project(paginated, fields)
    return GenreList(genres=projected, total=total, offset=0, has_more=has_more)


optimize_tool_schemas(mcp)
