# blackroad-game-engine

> Entity-Component-System game engine with ASCII terminal renderer

Part of the [BlackRoad OS](https://blackroad.io) ecosystem — [BlackRoad-Interactive](https://github.com/BlackRoad-Interactive)

---

# blackroad-game-engine

> Entity-Component-System game engine with ASCII terminal renderer and SQLite persistence.

Part of **BlackRoad-Interactive** — production game and graphics infrastructure.

## Architecture

```
World
├── Entity (id, components: dict)
│   ├── Position(x, y)
│   ├── Velocity(vx, vy)
│   ├── Health(hp, max_hp)
│   ├── Sprite(symbol, color)
│   ├── BoundingBox(width, height)
│   └── Tag(set[str])
├── Systems (sorted by priority)
│   ├── MovementSystem   — integrates velocity → position, bound bouncing
│   ├── CollisionSystem  — AABB broad-phase, emits collision events
│   ├── HealthSystem     — deactivates dead entities, emits death events
│   └── RenderSystem     — ANSI ASCII terminal renderer
└── EventBus             — pub/sub, full history, SQLite persistence
```

## Quick Start

```python
from src.game_engine import World, MovementSystem, CollisionSystem, HealthSystem, RenderSystem
from src.game_engine import make_player, make_enemy, EventBus

world = World()
world.add_system(MovementSystem(bounds=(0, 0, 38, 18)))
world.add_system(CollisionSystem(world.event_bus))
world.add_system(HealthSystem(world.event_bus))
world.add_system(RenderSystem(width=40, height=20))

world.add_entity(make_player(5, 5))
world.add_entity(make_enemy(15, 8))

for _ in range(60):
    world.tick(1/20)
world.close()
```

## Run Demo

```bash
python src/game_engine.py
```

## Tests

```bash
pip install pytest
pytest tests/ -v
```

## CI

GitHub Actions · Python 3.11 + 3.12 · pytest + flake8 + coverage
