"""Tests for BlackRoad Game Engine ECS."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import math
import pytest
from game_engine import (
    Component, Entity, Position, Velocity, Health, Sprite, BoundingBox, Tag,
    MovementSystem, CollisionSystem, HealthSystem, RenderSystem,
    EventBus, World, make_player, make_enemy, make_pickup,
)


# ── Component tests ──────────────────────────────────────────────────────────

class TestPosition:
    def test_default_values(self):
        p = Position()
        assert p.x == 0.0 and p.y == 0.0

    def test_distance_to(self):
        a, b = Position(0, 0), Position(3, 4)
        assert math.isclose(a.distance_to(b), 5.0)

    def test_repr(self):
        assert "Position" in repr(Position(1, 2))


class TestVelocity:
    def test_speed(self):
        v = Velocity(3, 4)
        assert math.isclose(v.speed, 5.0)

    def test_normalize(self):
        v = Velocity(3, 4).normalize()
        assert math.isclose(math.sqrt(v.vx**2 + v.vy**2), 1.0)

    def test_zero_normalize(self):
        v = Velocity(0, 0).normalize()
        assert v.vx == 0 and v.vy == 0


class TestHealth:
    def test_clamps_hp(self):
        h = Health(150, 100)
        assert h.hp == 100

    def test_invalid_max_hp(self):
        with pytest.raises(ValueError):
            Health(10, 0)

    def test_take_damage(self):
        h = Health(50, 100)
        actual = h.take_damage(30)
        assert actual == 30 and h.hp == 20

    def test_take_damage_capped(self):
        h = Health(10, 100)
        actual = h.take_damage(999)
        assert actual == 10 and h.hp == 0

    def test_heal(self):
        h = Health(50, 100)
        h.heal(20)
        assert h.hp == 70

    def test_is_alive(self):
        h = Health(1, 10)
        assert h.is_alive
        h.take_damage(1)
        assert not h.is_alive

    def test_percent(self):
        h = Health(50, 100)
        assert math.isclose(h.percent, 0.5)


class TestSprite:
    def test_render_contains_symbol(self):
        s = Sprite("@", "green")
        assert "@" in s.render()


class TestTag:
    def test_has(self):
        t = Tag({"player", "hero"})
        assert t.has("player")
        assert not t.has("enemy")

    def test_add(self):
        t = Tag()
        t.add("enemy")
        assert t.has("enemy")


# ── Entity tests ──────────────────────────────────────────────────────────────

class TestEntity:
    def test_add_and_get(self):
        e = Entity()
        p = Position(1, 2)
        e.add(p)
        assert e.get(Position) is p

    def test_has(self):
        e = Entity()
        e.add(Position())
        assert e.has(Position)
        assert not e.has(Velocity)

    def test_remove(self):
        e = Entity()
        e.add(Position(3, 4))
        removed = e.remove(Position)
        assert isinstance(removed, Position)
        assert not e.has(Position)

    def test_unique_id(self):
        assert Entity().id != Entity().id

    def test_repr(self):
        e = Entity()
        e.add(Position())
        assert "Position" in repr(e)


# ── System tests ──────────────────────────────────────────────────────────────

class TestMovementSystem:
    def test_moves_entity(self):
        e = Entity()
        e.add(Position(0, 0))
        e.add(Velocity(10, 5))
        MovementSystem().update([e], 1.0)
        assert math.isclose(e.get(Position).x, 10.0)
        assert math.isclose(e.get(Position).y, 5.0)

    def test_bounce_off_bounds(self):
        e = Entity()
        e.add(Position(0, 0))
        e.add(Velocity(-5, 0))
        MovementSystem(bounds=(0, 0, 10, 10)).update([e], 1.0)
        assert e.get(Velocity).vx > 0

    def test_skips_inactive(self):
        e = Entity()
        e.active = False
        e.add(Position(0, 0))
        e.add(Velocity(10, 0))
        MovementSystem().update([e], 1.0)
        assert e.get(Position).x == 0.0


class TestCollisionSystem:
    def test_detects_collision(self):
        bus = EventBus()
        collisions = []
        bus.subscribe("collision", lambda e: collisions.append(e))
        system = CollisionSystem(bus)

        a = Entity()
        a.add(Position(0, 0))
        a.add(BoundingBox(2, 2))

        b = Entity()
        b.add(Position(0.5, 0))
        b.add(BoundingBox(2, 2))

        system.update([a, b], 0.016)
        assert len(collisions) == 1

    def test_no_collision_when_apart(self):
        bus = EventBus()
        collisions = []
        bus.subscribe("collision", lambda e: collisions.append(e))
        system = CollisionSystem(bus)

        a = Entity()
        a.add(Position(0, 0))
        a.add(BoundingBox(1, 1))

        b = Entity()
        b.add(Position(100, 100))
        b.add(BoundingBox(1, 1))

        system.update([a, b], 0.016)
        assert len(collisions) == 0


class TestHealthSystem:
    def test_deactivates_dead_entities(self):
        bus = EventBus()
        system = HealthSystem(bus)
        e = Entity()
        e.add(Health(0, 100))
        system.update([e], 0.016)
        assert not e.active

    def test_emits_death_event(self):
        bus = EventBus()
        deaths = []
        bus.subscribe("entity_died", lambda ev: deaths.append(ev))
        system = HealthSystem(bus)
        e = Entity()
        e.add(Health(0, 100))
        system.update([e], 0.016)
        assert len(deaths) == 1


# ── EventBus tests ────────────────────────────────────────────────────────────

class TestEventBus:
    def test_emit_and_receive(self):
        bus = EventBus()
        received = []
        bus.subscribe("test", lambda e: received.append(e))
        bus.emit("test", {"value": 42})
        assert len(received) == 1
        assert received[0]["data"]["value"] == 42

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        handler = lambda e: received.append(e)
        bus.subscribe("test", handler)
        bus.unsubscribe("test", handler)
        bus.emit("test", {})
        assert len(received) == 0

    def test_history(self):
        bus = EventBus()
        bus.emit("a", {})
        bus.emit("b", {})
        assert len(bus.history) == 2

    def test_clear_history(self):
        bus = EventBus()
        bus.emit("a", {})
        bus.clear_history()
        assert len(bus.history) == 0


# ── World tests ───────────────────────────────────────────────────────────────

class TestWorld:
    def test_create_and_count(self):
        w = World()
        w.create_entity(Position(1, 1), Velocity(0, 0))
        assert w.entity_count == 1
        w.close()

    def test_remove_entity(self):
        w = World()
        e = w.create_entity(Position())
        assert w.remove_entity(e.id)
        w.close()

    def test_query(self):
        w = World()
        w.create_entity(Position(), Velocity())
        w.create_entity(Position())
        result = w.query(Position, Velocity)
        assert len(result) == 1
        w.close()

    def test_tick_advances_count(self):
        w = World()
        w.tick(0.016)
        assert w.tick_count == 1
        w.close()

    def test_dead_entities_purged(self):
        w = World()
        bus = w.event_bus
        w.add_system(HealthSystem(bus))
        e = w.create_entity(Health(0, 10))
        w.tick(0.016)
        assert w.entity_count == 0
        w.close()

    def test_render_system(self):
        w = World()
        w.add_system(RenderSystem(width=20, height=10))
        w.create_entity(Position(5, 5), Sprite("@", "white"))
        frame = w.render()
        assert frame is not None
        assert any("@" in row for row in frame)
        w.close()


# ── Factory tests ─────────────────────────────────────────────────────────────

class TestFactories:
    def test_make_player(self):
        e = make_player(3, 4)
        assert e.has(Position, Velocity, Health, Sprite)
        assert e.get(Tag).has("player")

    def test_make_enemy(self):
        e = make_enemy(5, 5)
        assert e.has(Position, Velocity, Health, Sprite)
        assert e.get(Tag).has("enemy")

    def test_make_pickup(self):
        e = make_pickup(2, 2)
        assert e.get(Tag).has("pickup")
