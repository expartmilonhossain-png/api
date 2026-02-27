from fastapi import APIRouter
from app.models.explore_models import ExploreConfigResponse, ExploreConfigData, ExploreCategoryResponse, ExploreSourceResponse

router = APIRouter()

# Default Explore Categories
EXPLORE_CATEGORIES = [
    ExploreCategoryResponse(id="all", label="All"),
    ExploreCategoryResponse(id="free", label="Free"),
    ExploreCategoryResponse(id="paid", label="Paid"),
    ExploreCategoryResponse(id="verified", label="World"),
]

# Default Explore Sources
EXPLORE_SOURCES = [
    ExploreSourceResponse(
        baseUrl="https://masa49.org/",
        nickname="Masa49",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/logo%20(1).png",
        accentColor="#7C4DFF",
        category="free",
        isVerified=False,
        hasCategories=True,
        searchUrlTemplate="https://masa49.org/?s={query}",
        sourceId="masa",
    ),
    ExploreSourceResponse(
        baseUrl="https://xhamster.com/",
        nickname="xHamster",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/favicon.ico",
        accentColor="#FF5252",
        category="free",
        isVerified=False,
        hasCategories=True,
        searchUrlTemplate="https://xhamster.com/search/videos?q={query}",
        sourceId="xhamster",
    ),
    ExploreSourceResponse(
        baseUrl="https://www.xnxx.com/",
        nickname="XNXX",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/favicon%20(1).ico",
        accentColor="#448AFF",
        category="free",
        isVerified=True,
        hasCategories=True,
        searchUrlTemplate="https://www.xnxx.com/search/{query}",
        sourceId="xnxx",
    ),
    ExploreSourceResponse(
        baseUrl="https://www.xvideos.com/",
        nickname="XVideos",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/favicon%20(2).ico",
        accentColor="#FFAB40",
        category="free",
        isVerified=True,
        hasCategories=True,
        searchUrlTemplate="https://www.xvideos.com/?k={query}",
        sourceId="xvideos",
    ),
    ExploreSourceResponse(
        baseUrl="https://www.pornhub.com/",
        nickname="Pornhub",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/favicon%20(3).ico",
        accentColor="#FF9100",
        category="free",
        isVerified=False,
        hasCategories=True,
        searchUrlTemplate="https://www.pornhub.com/video/search?search={query}",
        sourceId="pornhub",
    ),
    ExploreSourceResponse(
        baseUrl="https://www.youporn.com/",
        nickname="YouPorn",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/favicon%20(4).ico",
        accentColor="#FF4081",
        category="free",
        isVerified=False,
        hasCategories=True,
        searchUrlTemplate="https://www.youporn.com/search/?query={query}",
        sourceId="youporn",
    ),
    ExploreSourceResponse(
        baseUrl="https://www.redtube.com/",
        nickname="RedTube",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/favicon%20(5).ico",
        accentColor="#D32F2F",
        category="free",
        isVerified=False,
        hasCategories=True,
        searchUrlTemplate="https://www.redtube.com/?search={query}",
        sourceId="redtube",
    ),
    ExploreSourceResponse(
        baseUrl="https://beeg.com/",
        nickname="Beeg",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/logo%20(2).png",
        accentColor="#00BFA5",
        category="free",
        isVerified=False,
        hasCategories=True,
        searchUrlTemplate="https://beeg.com/?f={query}",
        sourceId="beeg",
    ),
    ExploreSourceResponse(
        baseUrl="https://spankbang.com/",
        nickname="SpankBang",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/favicon%20(6).ico",
        accentColor="#FFC107",
        category="free",
        isVerified=False,
        hasCategories=True,
        searchUrlTemplate="https://spankbang.com/s/{query}/",
        sourceId="spankbang",
    ),
    ExploreSourceResponse(
        baseUrl="https://fapnut.net/",
        nickname="OnlyFans",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/favicon%20(7).ico",
        accentColor="#00AFF0",
        category="paid",
        isVerified=False,
        hasCategories=True,
        searchUrlTemplate="https://fapnut.net/?s={query}",
        sourceId="fapnut",
    ),
    ExploreSourceResponse(
        baseUrl="https://pornxp.io/",
        nickname="PornXP",
        favicon="https://raw.githubusercontent.com/milon4999/apphub-release/refs/heads/main/logo/favicon.png",
        accentColor="#1a2137",
        category="free",
        isVerified=False,
        hasCategories=True,
        searchUrlTemplate="https://pornxp.io/search?q={query}",
        sourceId="pornxp",
    ),
]

EXPLORE_CONFIG = ExploreConfigData(
    title="SOURCES",
    categories=EXPLORE_CATEGORIES,
    sources=EXPLORE_SOURCES
)

@router.get("/explore/config", response_model=ExploreConfigResponse, tags=["Explore"])
async def get_explore_config() -> ExploreConfigResponse:
    """
    Get the configuration for the Explore Page, including available categories and sources.
    This allows the Explore page to be fully backend-driven.
    """
    return ExploreConfigResponse(
        status="success",
        data=EXPLORE_CONFIG
    )
