"""Eksempeldata til demonstration.

Kør:  python -m app.seed          (indlæser kun, hvis databasen er tom)
      python -m app.seed --force  (tilføjer eksempeldata uanset indhold)
"""

from __future__ import annotations

import sys

from .config import load_settings
from .db import Database
from .schemas import ItemCreate
from .services import Actor, create_item, init_meta, is_empty

DEMO_ITEMS = [
    dict(title="Velkomst ved formanden", item_type="speech", duration_seconds=300,
         description="Formanden byder velkommen.",
         technical_notes="Talerpult-mikrofon. Formanden sidder på første række."),
    dict(title="Intro-video", item_type="video", duration_seconds=95,
         description="Åbningsfilm.",
         technical_notes="Video med lyd – klargør afspiller. Lys ned i salen."),
    dict(title="Valg af dirigent", item_type="speech", duration_seconds=180,
         technical_notes="Trådløs håndholdt mikrofon."),
    dict(title="Bestyrelsens beretning", item_type="speech", duration_seconds=1200,
         description="Beretning ved formanden, efterfulgt af spørgsmål.",
         technical_notes="Talerpult + to håndholdte mikrofoner til spørgsmål i salen."),
    dict(title="Årets projekter – video", item_type="video", duration_seconds=240, optional=True,
         technical_notes="Video med lyd. Undertekster indbrændt."),
    dict(title="Hilsen fra samarbejdspartner", item_type="speech", duration_seconds=300, optional=True,
         description="Kun hvis tiden tillader det.",
         technical_notes="Gæstetaler venter ved scenetrappen. Håndholdt mikrofon."),
    dict(title="Fremlæggelse af regnskab", item_type="speech", duration_seconds=900,
         description="Kasserer fremlægger.",
         technical_notes="Taler står ved indgang B. Slides fra USB."),
    dict(title="Indkomne forslag", item_type="other", duration_seconds=1500,
         technical_notes="To personer på scenen. Mikrofon i salen til debat."),
    dict(title="Valg til bestyrelsen", item_type="other", duration_seconds=1200,
         technical_notes="Stemmesedler uddeles. Resultatslide klar."),
    dict(title="Eventuelt", item_type="speech", duration_seconds=600,
         technical_notes="Håndholdte mikrofoner i salen."),
    dict(title="Afslutning", item_type="speech", duration_seconds=180,
         technical_notes="Musik ud efter sidste ord."),
]


def seed(db: Database, *, force: bool = False) -> int:
    if not force and not is_empty(db):
        return 0
    actor = Actor(role="system", username="seed")
    for data in DEMO_ITEMS:
        create_item(db, ItemCreate(**data), actor)
    return len(DEMO_ITEMS)


def main() -> None:
    settings = load_settings()
    db = Database(settings.database_path)
    db.create_all()
    init_meta(db)
    n = seed(db, force="--force" in sys.argv)
    print(f"Indlæste {n} eksempelpunkter i {settings.database_path}" if n
          else "Databasen indeholder allerede punkter – intet indlæst (brug --force).")
    db.dispose()


if __name__ == "__main__":
    main()
