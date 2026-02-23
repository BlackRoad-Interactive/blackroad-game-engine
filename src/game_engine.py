"""
BlackRoad Game Engine — Entity-Component-System Architecture
Production-grade ECS engine with ASCII terminal renderer and SQLite persistence.
"""
from __future__ import annotations
import math
import os
import sqlite3
import sys
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type

# ─── ANSI colours ───────────────────────────────────────────────────────────
RESET  = "\033[0m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
BLUE   = "\033[34m"
CYAN   = "\033[36m"
WHITE  = "\033[37m"
BOLD   = "\033[1m"

COLOUR_MAP: Dict[str, str] = {
    "red": RED, "green": GREEN, "yellow": YELLOW,
    "blue": BLUE, "cyan": CYAN, "white": WHITE,
}

# ─── Components ─────────────────────────────────────────────────────────────

class Component:
    """Base class for all ECS components."""
    pass


@dataclass
class Position(Component):
    x: float = 0.0
    y: float = 0.0

    def distance_to(self, other: "Position") -> float:
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def __repr__(self) -> str:
        return f"Position({self.x:.2f}, {self.y:.2f})"


@dataclass
class Velocity(Component):
    vx: float = 0.0
    vy: float = 0.0

    @property
    def speed(self) -> float:
        return math.sqrt(self.vx ** 2 + self.vy ** 2)

    def normalize(self) -> "Velocity":
        s = self.speed
        if s == 0:
            return Velocity(0.0, 0.0)
        return Velocity(self.vx / s, self.vy / s)

    def __repr__(self) -> str:
        return f"Velocity({self.vx:.2f}, {self.vy:.2f})"


@dataclass
class Health(Component):
    hp: float
    max_hp: float

    def __post_init__(self) -> None:
        if self.max_hp <= 0:
            raise ValueError("max_hp must be positive")
        self.hp = min(self.hp, self.max_hp)

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    @property
    def percent(self) -> float:
        return self.hp / self.max_hp

    def take_damage(self, amount: float) -> float:
        """Apply damage; returns actual damage dealt."""
        actual = min(amount, self.hp)
        self.hp -= actual
        return actual

    def heal(self, amount: float) -> float:
        """Heal; returns actual amount healed."""
        actual = min(amount, self.max_hp - self.hp)
        self.hp += actual
        return actual

    def __repr__(self) -> str:
        return f"Health({self.hp:.1f}/{self.max_hp:.1f})"


@dataclass
class Sprite(Component):
    symbol: str = "@"
    color: str = "white"

    def render(self) -> str:
        ansi = COLOUR_MAP.get(self.color, WHITE)
        return f"{ansi}{self.symbol}{RESET}"


@dataclass
class BoundingBox(Component):
    width: float = 1.0
    height: float = 1.0

    def contains(self, pos: Position, target: Position) -> bool:
        return (
            abs(pos.x - target.x) <= self.width / 2
            and abs(pos.y - target.y) <= self.height / 2
        )


@dataclass
class Tag(Component):
    tags: Set[str] = field(default_factory=set)

    def add(self, tag: str) -> None:
        self.tags.add(tag)

    def has(self, tag: str) -> bool:
        return tag in self.tags


# ─── Entity ─────────────────────────────────────────────────────────────────

class Entity:
    """A game entity — just an ID plus a bag of components."""

    def __init__(self, entity_id: Optional[str] = None) -> None:
        self.id: str = entity_id or str(uuid.uuid4())[:8]
        self.components: Dict[Type[Component], Component] = {}
        self.active: bool = True

    def add(self, component: Component) -> "Entity":
        self.components[type(component)] = component
        return self

    def remove(self, comp_type: Type[Component]) -> Optional[Component]:
        return self.components.pop(comp_type, None)

    def get(self, comp_type: Type[Component]) -> Optional[Component]:
        return self.components.get(comp_type)

    def has(self, *comp_types: Type[Component]) -> bool:
        return all(ct in self.components for ct in comp_types)

    def __repr__(self) -> str:
        comp_names = [c.__class__.__name__ for c in self.components.values()]
        return f"Entity({self.id!r}, [{', '.join(comp_names)}])"


# ─── Systems ─────────────────────────────────────────────────────────────────

class System(ABC):
    """Base class for all ECS systems."""
    priority: int = 0  # lower = runs first

    @abstractmethod
    def update(self, entities: List[Entity], dt: float) -> None:
        pass


class MovementSystem(System):
    """Applies velocity to position each tick."""
    priority = 10

    def __init__(self, bounds: Optional[Tuple[float, float, float, float]] = None) -> None:
        # bounds = (min_x, min_y, max_x, max_y)
        self.bounds = bounds

    def update(self, entities: List[Entity], dt: float) -> None:
        for entity in entities:
            if not entity.active:
                continue
            pos = entity.get(Position)
            vel = entity.get(Velocity)
            if pos is None or vel is None:
                continue
            pos.x += vel.vx * dt
            pos.y += vel.vy * dt
            if self.bounds:
                min_x, min_y, max_x, max_y = self.bounds
                if pos.x < min_x or pos.x > max_x:
                    vel.vx = -vel.vx
                    pos.x = max(min_x, min(max_x, pos.x))
                if pos.y < min_y or pos.y > max_y:
                    vel.vy = -vel.vy
                    pos.y = max(min_y, min(max_y, pos.y))


class CollisionSystem(System):
    """AABB collision detection, emits collision events."""
    priority = 20

    def __init__(self, event_bus: "EventBus") -> None:
        self.event_bus = event_bus
        self._pairs_this_tick: Set[Tuple[str, str]] = set()

    def update(self, entities: List[Entity], dt: float) -> None:
        self._pairs_this_tick.clear()
        active = [e for e in entities if e.active and e.has(Position, BoundingBox)]
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                if self._colliding(a, b):
                    pair = tuple(sorted([a.id, b.id]))
                    if pair not in self._pairs_this_tick:
                        self._pairs_this_tick.add(pair)
                        self.event_bus.emit("collision", {"a": a, "b": b})

    @staticmethod
    def _colliding(a: Entity, b: Entity) -> bool:
        pa, pb = a.get(Position), b.get(Position)
        ba, bb = a.get(BoundingBox), b.get(BoundingBox)
        return (
            abs(pa.x - pb.x) < (ba.width + bb.width) / 2
            and abs(pa.y - pb.y) < (ba.height + bb.height) / 2
        )


class HealthSystem(System):
    """Removes dead entities and emits death events."""
    priority = 30

    def __init__(self, event_bus: "EventBus") -> None:
        self.event_bus = event_bus

    def update(self, entities: List[Entity], dt: float) -> None:
        for entity in entities:
            if not entity.active:
                continue
            health = entity.get(Health)
            if health is not None and not health.is_alive:
                entity.active = False
                self.event_bus.emit("entity_died", {"entity": entity})


class RenderSystem(System):
    """ASCII terminal renderer — draws the game world."""
    priority = 100

    def __init__(self, width: int = 40, height: int = 20) -> None:
        self.width = width
        self.height = height
        self._buffer: List[List[str]] = []
        self._clear_buffer()

    def _clear_buffer(self) -> None:
        self._buffer = [[" " for _ in range(self.width)] for _ in range(self.height)]

    def update(self, entities: List[Entity], dt: float) -> None:
        self._clear_buffer()
        renderables = sorted(
            [e for e in entities if e.active and e.has(Position, Sprite)],
            key=lambda e: e.get(Position).y,
        )
        for entity in renderables:
            pos = entity.get(Position)
            sprite = entity.get(Sprite)
            col = int(round(pos.x))
            row = int(round(pos.y))
            if 0 <= col < self.width and 0 <= row < self.height:
                self._buffer[row][col] = sprite.render()
        self._flush()

    def _flush(self) -> None:
        border = "+" + "-" * self.width + "+"
        lines = [border]
        for row in self._buffer:
            lines.append("|" + "".join(row) + "|")
        lines.append(border)
        # Move cursor to top-left to redraw in place
        sys.stdout.write("\033[H")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()

    def get_frame(self) -> List[str]:
        """Return the current frame as a list of strings (for testing)."""
        return ["".join(row) for row in self._buffer]


# ─── EventBus ────────────────────────────────────────────────────────────────

class EventBus:
    """Simple synchronous publish/subscribe event bus."""

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._history: List[Dict[str, Any]] = []

    def subscribe(self, event_type: str, handler: Callable[[Dict[str, Any]], None]) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type] = [
            h for h in self._handlers[event_type] if h is not handler
        ]

    def emit(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        payload = {"type": event_type, "data": data or {}, "ts": time.time()}
        self._history.append(payload)
        for handler in self._handlers.get(event_type, []):
            handler(payload)

    def clear_history(self) -> None:
        self._history.clear()

    @property
    def history(self) -> List[Dict[str, Any]]:
        return list(self._history)


# ─── World ───────────────────────────────────────────────────────────────────

class World:
    """
    The ECS world — owns entities, systems, event bus, and the SQLite store.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._entities: Dict[str, Entity] = {}
        self._systems: List[System] = []
        self.event_bus = EventBus()
        self._db = self._init_db(db_path)
        self._tick_count: int = 0
        self._elapsed: float = 0.0

    # ── DB setup ──────────────────────────────────────────────────────────
    def _init_db(self, path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                active INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS components (
                entity_id TEXT NOT NULL,
                comp_type TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (entity_id, comp_type),
                FOREIGN KEY (entity_id) REFERENCES entities(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                data TEXT,
                tick INTEGER NOT NULL,
                ts REAL NOT NULL
            )
        """)
        conn.commit()
        return conn

    def _persist_entity(self, entity: Entity) -> None:
        import json
        self._db.execute(
            "INSERT OR REPLACE INTO entities (id, active, created_at) VALUES (?,?,?)",
            (entity.id, int(entity.active), time.time()),
        )
        for comp_type, comp in entity.components.items():
            self._db.execute(
                "INSERT OR REPLACE INTO components (entity_id, comp_type, data) VALUES (?,?,?)",
                (entity.id, comp_type.__name__, json.dumps(comp.__dict__)),
            )
        self._db.commit()

    # ── Entity management ─────────────────────────────────────────────────
    def create_entity(self, *components: Component) -> Entity:
        entity = Entity()
        for comp in components:
            entity.add(comp)
        self._entities[entity.id] = entity
        self._persist_entity(entity)
        self.event_bus.emit("entity_created", {"entity": entity})
        return entity

    def add_entity(self, entity: Entity) -> Entity:
        self._entities[entity.id] = entity
        self._persist_entity(entity)
        return entity

    def remove_entity(self, entity_id: str) -> bool:
        entity = self._entities.pop(entity_id, None)
        if entity:
            entity.active = False
            self.event_bus.emit("entity_removed", {"entity_id": entity_id})
            return True
        return False

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self._entities.get(entity_id)

    def query(self, *comp_types: Type[Component]) -> List[Entity]:
        """Return all active entities that have all requested component types."""
        return [
            e for e in self._entities.values()
            if e.active and e.has(*comp_types)
        ]

    # ── System management ─────────────────────────────────────────────────
    def add_system(self, system: System) -> None:
        self._systems.append(system)
        self._systems.sort(key=lambda s: s.priority)

    def remove_system(self, system_type: Type[System]) -> bool:
        before = len(self._systems)
        self._systems = [s for s in self._systems if not isinstance(s, system_type)]
        return len(self._systems) < before

    # ── Main loop ─────────────────────────────────────────────────────────
    def tick(self, dt: float = 1 / 60) -> None:
        self._tick_count += 1
        self._elapsed += dt
        entities = list(self._entities.values())
        for system in self._systems:
            system.update(entities, dt)
        # Purge inactive entities
        dead = [eid for eid, e in self._entities.items() if not e.active]
        for eid in dead:
            self._entities.pop(eid)

    def render(self) -> Optional[List[str]]:
        """Explicitly invoke the RenderSystem (if registered)."""
        for sys_ in self._systems:
            if isinstance(sys_, RenderSystem):
                entities = list(self._entities.values())
                sys_.update(entities, 0)
                return sys_.get_frame()
        return None

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def tick_count(self) -> int:
        return self._tick_count

    def close(self) -> None:
        self._db.close()

    def __repr__(self) -> str:
        return (
            f"World(entities={self.entity_count}, "
            f"systems={len(self._systems)}, "
            f"tick={self._tick_count})"
        )


# ─── Factory helpers ─────────────────────────────────────────────────────────

def make_player(x: float = 0.0, y: float = 0.0) -> Entity:
    e = Entity()
    e.add(Position(x, y))
    e.add(Velocity(0, 0))
    e.add(Health(100, 100))
    e.add(Sprite("@", "green"))
    e.add(BoundingBox(1, 1))
    e.add(Tag({"player"}))
    return e


def make_enemy(x: float, y: float, vx: float = 1.0, vy: float = 0.5) -> Entity:
    e = Entity()
    e.add(Position(x, y))
    e.add(Velocity(vx, vy))
    e.add(Health(30, 30))
    e.add(Sprite("X", "red"))
    e.add(BoundingBox(1, 1))
    e.add(Tag({"enemy"}))
    return e


def make_pickup(x: float, y: float) -> Entity:
    e = Entity()
    e.add(Position(x, y))
    e.add(Sprite("*", "yellow"))
    e.add(BoundingBox(0.5, 0.5))
    e.add(Tag({"pickup"}))
    return e


# ─── Demo runner ─────────────────────────────────────────────────────────────

def run_demo(ticks: int = 60, sleep_s: float = 0.05) -> World:
    """Run a short demo: player, enemies and pickups bouncing around."""
    world = World()
    bus = world.event_bus
    deaths: List[str] = []

    def on_death(evt: Dict[str, Any]) -> None:
        deaths.append(evt["data"]["entity"].id)

    bus.subscribe("entity_died", on_death)

    # Systems
    bounds = (0, 0, 38, 18)
    world.add_system(MovementSystem(bounds=bounds))
    world.add_system(CollisionSystem(bus))
    world.add_system(HealthSystem(bus))
    render = RenderSystem(width=40, height=20)
    world.add_system(render)

    # Entities
    world.add_entity(make_player(5, 5))
    for i in range(3):
        world.add_entity(make_enemy(10 + i * 5, 5 + i * 3, vx=1.5 - i * 0.5, vy=0.8 + i * 0.3))
    for i in range(5):
        world.add_entity(make_pickup(3 + i * 7, 3 + i * 2))

    os.system("clear" if os.name == "posix" else "cls")
    sys.stdout.write("\033[?25l")  # hide cursor
    try:
        for _ in range(ticks):
            world.tick(1 / 20)
            time.sleep(sleep_s)
    finally:
        sys.stdout.write("\033[?25h")  # show cursor
        print(f"\n{BOLD}Demo complete.{RESET} Ticks: {world.tick_count}, Deaths: {len(deaths)}")

    world.close()
    return world


if __name__ == "__main__":
    run_demo()
