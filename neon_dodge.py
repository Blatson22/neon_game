import sys
import math
import os
import time
import random
import struct
import wave
import shutil
import tempfile

import raylib as rl


W, H = 720, 1280
FIT_MARGIN = 60

BG = (10, 9, 24, 255)
BG_TOP = (18, 12, 40, 255)
BG_HOT = (46, 14, 70, 255)
CYAN = (0, 240, 255, 255)
MAGENTA = (255, 0, 160, 255)
RED_N = (255, 60, 90, 255)
GOLD = (255, 205, 0, 255)
WHITE = (245, 245, 245, 255)
DIM = (150, 150, 170, 255)
PURPLE = (120, 70, 255, 255)

PLAYER_R = 26
PLAYER_Y = H - 150
PLAYER_SPEED = 850.0

SPAWN_EASY = 0.95
SPAWN_HARD = 0.30
FALL_EASY = 430.0
FALL_HARD = 1150.0
MARGIN = 30

MENU = "MENU"
PLAYING = "PLAYING"
GAME_OVER = "GAME_OVER"

SAMPLE_RATE = 44100

best_score = 0


def _clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def lerp_color(c1, c2, t):
    t = _clamp(t, 0.0, 1.0)
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(4))


def circle_rect_collision(cx, cy, r, rx, ry, rw, rh):
    nx = _clamp(cx, rx, rx + rw)
    ny = _clamp(cy, ry, ry + rh)
    dx = cx - nx
    dy = cy - ny
    return dx * dx + dy * dy <= r * r


def circles_collide(x1, y1, r1, x2, y2, r2):
    dx = x1 - x2
    dy = y1 - y2
    rr = r1 + r2
    return dx * dx + dy * dy <= rr * rr


def _write_wav(path, frames):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(frames)


def _gen_pop(tmpdir):
    sr = SAMPLE_RATE
    n = int(sr * 0.09)
    out = bytearray()
    phase = 0.0
    for i in range(n):
        f = 1000.0 - 750.0 * (i / n)
        phase += 2.0 * math.pi * f / sr
        env = (1.0 - i / n) ** 2
        v = math.sin(phase) * env
        out += struct.pack("<h", int(_clamp(v, -1.0, 1.0) * 32767))
    path = os.path.join(tmpdir, "pop.wav")
    _write_wav(path, bytes(out))
    return path


def _gen_boom(tmpdir):
    sr = SAMPLE_RATE
    n = int(sr * 0.4)
    out = bytearray()
    phase = 0.0
    rng = random.Random(1234)
    for i in range(n):
        t = i / sr
        f = 90.0 - 40.0 * (i / n)
        phase += 2.0 * math.pi * f / sr
        env = math.exp(-t / 0.12)
        v = (math.sin(phase) + 0.5 * (rng.random() * 2.0 - 1.0)) * env
        out += struct.pack("<h", int(_clamp(v, -1.0, 1.0) * 32767))
    path = os.path.join(tmpdir, "boom.wav")
    _write_wav(path, bytes(out))
    return path


def init_audio():
    sounds = {}
    tmpdir = None
    try:
        rl.InitAudioDevice()
        if rl.IsAudioDeviceReady():
            tmpdir = tempfile.mkdtemp(prefix="neondodge_")
            sounds["pop"] = rl.LoadSound(_gen_pop(tmpdir).encode())
            sounds["boom"] = rl.LoadSound(_gen_boom(tmpdir).encode())
            rl.SetMasterVolume(0.55)
    except Exception:
        sounds = {}
    return sounds, tmpdir


def cleanup_audio(sounds, tmpdir):
    try:
        for s in sounds.values():
            rl.UnloadSound(s)
        rl.CloseAudioDevice()
    except Exception:
        pass
    if tmpdir:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


class Game:
    def __init__(self):
        self.reset_all()

    def reset_all(self):
        self.state = MENU
        self.score = 0.0
        self.elapsed = 0.0
        self.difficulty = 0.0
        self.spawn_timer = 0.5
        self.obstacles = []
        self.particles = []
        self.popups = []
        self.sound_queue = []
        self.shake = 0.0
        self.flash = 0.0
        self.score_pop = 0.0
        self.px = W / 2.0
        self.py = float(PLAYER_Y)
        self.pvx = 0.0
        self.squash = 0.0
        self.pulse = 0.0
        self.dead_timer = 0.0
        self.obstacles_spawned = 0
        self.near_misses = 0
        self.died = False

    def _rnd(self, a, b):
        return rl.GetRandomValue(a, b)

    def _start_run(self):
        self.reset_all()
        self.state = PLAYING

    def _half_w(self, o):
        return o["r"] if o["tipo"] == "bomb" else o["hw"]

    def _half_h(self, o):
        return o["r"] if o["tipo"] == "bomb" else o["hh"]

    def update(self, dt, inputs):
        self.pulse += dt
        self._update_effects(dt)

        if self.state == MENU:
            if self._rnd(0, 100) < 4:
                self._spawn_ambient()
            if inputs.get("space_pressed") or inputs.get("enter_pressed"):
                self._start_run()

        elif self.state == PLAYING:
            if inputs.get("r_pressed"):
                self._start_run()
                return
            self._update_playing(dt, inputs)

        elif self.state == GAME_OVER:
            self.dead_timer += dt
            can_retry = self.dead_timer >= 0.6
            if can_retry and (
                inputs.get("space_pressed")
                or inputs.get("enter_pressed")
                or inputs.get("r_pressed")
            ):
                self._start_run()

    def _update_effects(self, dt):
        self.shake *= math.exp(-dt * 6.0)
        if self.shake < 0.05:
            self.shake = 0.0
        if self.flash > 0.0:
            self.flash = max(0.0, self.flash - dt * 2.8)
        if self.score_pop > 0.0:
            self.score_pop = max(0.0, self.score_pop - dt * 3.5)

        for p in self.particles:
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += p["gravity"] * dt
            p["life"] -= dt
        self.particles = [p for p in self.particles if p["life"] > 0.0]

        for p in self.popups:
            p["life"] -= dt
            p["y"] += p.get("vy", -60.0) * dt
        self.popups = [p for p in self.popups if p["life"] > 0.0]

    def _update_playing(self, dt, inputs):
        self.elapsed += dt
        self.difficulty = 1.0 - math.exp(-self.elapsed / 22.0)

        self._update_player(dt, inputs)
        self._update_spawning(dt)
        self._update_obstacles(dt)

        if self.state != PLAYING:
            return

        self.score += dt * 12.0 * (1.0 + self.difficulty)
        self._spawn_trail()

    def _update_player(self, dt, inp):
        if inp.get("mouse_moved"):
            tx = float(inp.get("mouse_x", self.px))
            self.pvx = (tx - self.px) * min(1.0, dt * 28.0)
        else:
            target = 0.0
            if inp.get("left"):
                target -= PLAYER_SPEED
            if inp.get("right"):
                target += PLAYER_SPEED
            self.pvx += (target - self.pvx) * min(1.0, dt * 12.0)

        self.px += self.pvx * dt
        self.px = _clamp(self.px, PLAYER_R, W - PLAYER_R)
        self.squash = _clamp(abs(self.pvx) / PLAYER_SPEED, 0.0, 1.0)

    def _update_spawning(self, dt):
        self.spawn_timer -= dt
        if self.spawn_timer <= 0.0:
            self._spawn_wave()
            interval = SPAWN_HARD + (SPAWN_EASY - SPAWN_HARD) * (1.0 - self.difficulty)
            self.spawn_timer = interval * self._rnd(85, 115) / 100.0

    def _spawn_wave(self):
        n = 1
        if self.difficulty > 0.2 and self._rnd(0, 100) < int(self.difficulty * 30):
            n = 2
        if self.difficulty > 0.6 and self._rnd(0, 100) < int(self.difficulty * 20):
            n = 3
        for _ in range(n):
            self._spawn_obstacle()

    def _spawn_obstacle(self):
        speed = FALL_EASY + (FALL_HARD - FALL_EASY) * self.difficulty
        speed *= self._rnd(85, 120) / 100.0
        r = self._rnd(0, 9)
        color = MAGENTA if self._rnd(0, 1) == 0 else RED_N
        o = {
            "tipo": "block",
            "x": 0.0, "y": -200.0,
            "hw": 0.0, "hh": 0.0, "r": 0,
            "vy": speed,
            "vx": float(self._rnd(-45, 65)),
            "color": color,
            "passed": False,
            "spin": 0.0,
            "phase": self._rnd(0, 628) / 100.0,
        }
        if r < 4:
            w = self._rnd(60, 160)
            h = self._rnd(50, 110)
            o["hw"] = w / 2.0
            o["hh"] = h / 2.0
            o["x"] = float(self._rnd(MARGIN + int(w / 2), W - MARGIN - int(w / 2)))
        elif r < 7:
            s = self._rnd(70, 110)
            o["tipo"] = "spike"
            o["hw"] = s / 2.0
            o["hh"] = s / 2.0
            o["x"] = float(self._rnd(MARGIN + int(s / 2), W - MARGIN - int(s / 2)))
        else:
            rr = self._rnd(26, 44)
            o["tipo"] = "bomb"
            o["r"] = float(rr)
            o["hw"] = 0.0
            o["hh"] = 0.0
            o["x"] = float(self._rnd(MARGIN + rr, W - MARGIN - rr))
        self.obstacles.append(o)
        self.obstacles_spawned += 1

    def _update_obstacles(self, dt):
        for o in self.obstacles:
            o["y"] += o["vy"] * dt
            o["x"] += o["vx"] * dt
            o["x"] += math.sin(self.pulse * 2.0 + o["phase"]) * 30.0 * dt
            o["spin"] += dt * 3.0

            if self._collides(o):
                self._game_over()
                return

            hh = self._half_h(o)
            if not o["passed"] and (o["y"] - hh) > (self.py + PLAYER_R):
                o["passed"] = True
                hw = self._half_w(o)
                if abs(o["x"] - self.px) < (hw + PLAYER_R + 50):
                    self._on_near_miss(o)

        self.obstacles = [o for o in self.obstacles if o["y"] < H + 300]

    def _collides(self, o):
        t = o["tipo"]
        if t == "bomb":
            return circles_collide(self.px, self.py, PLAYER_R, o["x"], o["y"], o["r"])
        if t == "spike":
            return circle_rect_collision(
                self.px, self.py, PLAYER_R * 0.9,
                o["x"] - o["hw"] * 0.6, o["y"] - o["hh"] * 0.6,
                o["hw"] * 1.2, o["hh"] * 1.2,
            )
        return circle_rect_collision(
            self.px, self.py, PLAYER_R,
            o["x"] - o["hw"], o["y"] - o["hh"],
            o["hw"] * 2.0, o["hh"] * 2.0,
        )

    def _game_over(self):
        self.state = GAME_OVER
        self.died = True
        self.dead_timer = 0.0
        self.flash = 1.0
        self.shake = 28.0
        self.sound_queue.append("boom")
        self._spawn_explosion(self.px, self.py)
        global best_score
        best_score = max(best_score, int(self.score))

    def _on_near_miss(self, o):
        self.near_misses += 1
        bonus = 150.0 * (1.0 + self.difficulty)
        self.score += bonus
        self.score_pop = 1.0
        self.shake = max(self.shake, 8.0)
        self.sound_queue.append("pop")
        self._spawn_near_miss(o["x"], o["y"])
        y = self.py - 90.0
        self.popups.append({
            "text": "¡POR POCO!".encode("utf-8"), "x": o["x"], "y": y,
            "life": 0.8, "maxlife": 0.8, "size": 36, "color": GOLD, "vy": -60.0,
        })
        self.popups.append({
            "text": b"+%d" % int(bonus), "x": o["x"], "y": y + 34,
            "life": 0.8, "maxlife": 0.8, "size": 26, "color": WHITE, "vy": -60.0,
        })

    def _add_particle(self, x, y, vx, vy, life, size, color, gravity):
        self.particles.append({
            "x": x, "y": y, "vx": vx, "vy": vy,
            "life": life, "maxlife": life,
            "size": size, "color": color, "gravity": gravity,
        })

    def _spawn_trail(self):
        n = 3 if abs(self.pvx) > 200 else 2
        for _ in range(n):
            px = self.px + self._rnd(-10, 10)
            py = self.py + PLAYER_R + self._rnd(-4, 6)
            vx = -self.pvx * 0.1 + self._rnd(-30, 30)
            vy = self._rnd(20, 90)
            life = self._rnd(25, 50) / 100.0
            size = self._rnd(3, 7)
            self._add_particle(px, py, vx, vy, life, size, CYAN, 40.0)

    def _spawn_explosion(self, x, y):
        palette = [CYAN, MAGENTA, GOLD]
        for _ in range(110):
            ang = self._rnd(0, 628) / 100.0
            speed = self._rnd(120, 620)
            vx = math.cos(ang) * speed
            vy = math.sin(ang) * speed - 200.0
            color = palette[self._rnd(0, 2)]
            life = self._rnd(40, 95) / 100.0
            size = self._rnd(3, 8)
            self._add_particle(x, y, vx, vy, life, size, color, 300.0)

    def _spawn_near_miss(self, x, y):
        for _ in range(22):
            ang = self._rnd(0, 628) / 100.0
            speed = self._rnd(80, 360)
            vx = math.cos(ang) * speed
            vy = math.sin(ang) * speed - 60.0
            life = self._rnd(30, 60) / 100.0
            size = self._rnd(2, 5)
            self._add_particle(x, y, vx, vy, life, size, GOLD, 300.0)

    def _spawn_ambient(self):
        x = float(self._rnd(40, W - 40))
        y = -20.0
        vy = self._rnd(60, 180)
        color = PURPLE if self._rnd(0, 1) == 0 else CYAN
        life = 3.0
        size = self._rnd(2, 4)
        self._add_particle(x, y, 0.0, vy, life, size, color, 0.0)

    def current_bg(self):
        return lerp_color(BG, BG_HOT, self.difficulty * 0.6)

    def _shake_offset(self):
        if self.shake < 0.1:
            return 0.0, 0.0
        ox = (self._rnd(0, 2000) / 1000.0 - 1.0) * self.shake
        oy = (self._rnd(0, 2000) / 1000.0 - 1.0) * self.shake
        return ox, oy

    def _center(self, text, y, size, color):
        wtext = rl.MeasureText(text, size)
        rl.DrawText(text, (W - wtext) // 2, int(y), size, color)

    def draw(self):
        ox, oy = self._shake_offset()
        rl.BeginMode2D(((ox, oy), (0.0, 0.0), 0.0, 1.0))
        self._draw_background()
        self._draw_obstacles()
        self._draw_player()
        self._draw_particles()
        self._draw_ui()
        self._draw_popups()
        rl.EndMode2D()

        if self.flash > 0.01:
            a = int(200 * self.flash)
            rl.DrawRectangle(0, 0, W, H, (255, 255, 255, a))

    def _draw_background(self):
        t = self.pulse
        pulse = 0.5 + 0.5 * math.sin(t * 2.0)
        hot = self.difficulty

        col = lerp_color(BG_TOP, (70, 24, 100, 255), hot)
        a = int(70 + 60 * pulse + 50 * hot)
        rl.DrawRectangle(0, 0, W, 300, (col[0], col[1], col[2], min(255, a)))

        for i in range(6):
            yy = ((t * 90.0 + i * 213.0) % (H + 200)) - 100
            rl.DrawRectangle(0, int(yy), W, 1, (PURPLE[0], PURPLE[1], PURPLE[2], 18))

    def _draw_obstacles(self):
        for o in self.obstacles:
            if o["tipo"] == "block":
                self._draw_block(o)
            elif o["tipo"] == "spike":
                self._draw_spike(o)
            else:
                self._draw_bomb(o)

    def _draw_block(self, o):
        x, y, hw, hh = o["x"], o["y"], o["hw"], o["hh"]
        col = o["color"]
        rl.BeginBlendMode(rl.BLEND_ADDITIVE)
        rl.DrawRectangleRounded(
            (x - hw - 12, y - hh - 12, hw * 2.0 + 24, hh * 2.0 + 24),
            0.3, 8, (col[0], col[1], col[2], 70),
        )
        rl.EndBlendMode()
        rl.DrawRectangleRec((x - hw, y - hh, hw * 2.0, hh * 2.0), col)
        rl.DrawRectangleLinesEx(
            (x - hw, y - hh, hw * 2.0, hh * 2.0), 3, (255, 240, 255, 200),
        )

    def _draw_spike(self, o):
        x, y, hw, hh = o["x"], o["y"], o["hw"], o["hh"]
        col = o["color"]
        v1 = (x - hw, y - hh)
        v2 = (x + hw, y - hh)
        v3 = (x, y + hh)
        rl.BeginBlendMode(rl.BLEND_ADDITIVE)
        rl.DrawTriangle(
            (x - hw - 12, y - hh - 16), (x + hw + 12, y - hh - 16),
            (x, y + hh + 16), (col[0], col[1], col[2], 70),
        )
        rl.EndBlendMode()
        rl.DrawTriangle(v1, v2, v3, col)
        rl.DrawLineEx(v1, v2, 3, (255, 240, 255, 200))
        rl.DrawLineEx(v2, v3, 3, (255, 240, 255, 200))
        rl.DrawLineEx(v3, v1, 3, (255, 240, 255, 200))

    def _draw_bomb(self, o):
        x, y, r = o["x"], o["y"], o["r"]
        col = o["color"]
        rl.BeginBlendMode(rl.BLEND_ADDITIVE)
        rl.DrawCircleV((x, y), r + 12, (col[0], col[1], col[2], 70))
        rl.EndBlendMode()
        rl.DrawCircleV((x, y), r, col)
        rl.DrawRing((x, y), r - 7, r, 0, 360, 24, (255, 255, 255, 200))
        rl.DrawCircleV((x, y), r * 0.4, (255, 255, 255, 120))
        ang = o["spin"]
        rl.DrawCircleV(
            (x + math.cos(ang) * r * 0.6, y + math.sin(ang) * r * 0.6),
            3, WHITE,
        )

    def _draw_player(self):
        px, py, r = self.px, self.py, PLAYER_R
        s = self.squash
        rx = r * (1.0 + 0.28 * s)
        ry = r * (1.0 - 0.24 * s)

        rl.BeginBlendMode(rl.BLEND_ADDITIVE)
        rl.DrawCircleV((px, py), int(r * 2.4), (0, 120, 200, 45))
        rl.DrawCircleV((px, py), int(r * 1.5), (0, 180, 255, 70))
        rl.EndBlendMode()

        rl.DrawEllipse(int(px), int(py), rx, ry, CYAN)
        rl.DrawCircleV((px, py), int(r * 0.45), (230, 255, 255, 255))
        rl.DrawRing((px, py), rx + 3, rx + 7, 0, 360, 32, (255, 255, 255, 60))

    def _draw_particles(self):
        rl.BeginBlendMode(rl.BLEND_ADDITIVE)
        for p in self.particles:
            k = p["life"] / p["maxlife"]
            a = int(255 * k)
            s = max(1.0, p["size"] * k)
            c = p["color"]
            rl.DrawRectangle(
                int(p["x"] - s / 2), int(p["y"] - s / 2),
                int(s), int(s), (c[0], c[1], c[2], a),
            )
        rl.EndBlendMode()

    def _draw_ui(self):
        if self.state == MENU:
            self._draw_menu()
        elif self.state == PLAYING:
            self._draw_hud()
        elif self.state == GAME_OVER:
            self._draw_game_over()

    def _draw_hud(self):
        scale = 1.0 + 0.35 * self.score_pop
        fsize = int(84 * scale)
        col = lerp_color(GOLD, WHITE, 1.0 - self.score_pop)
        text = b"%d" % int(self.score)
        wtext = rl.MeasureText(text, fsize)
        rl.DrawText(text, (W - wtext) // 2, 40, fsize, col)
        bst = ("RÉCORD %d" % best_score).encode("utf-8")
        bw = rl.MeasureText(bst, 28)
        rl.DrawText(bst, (W - bw) // 2, 40 + fsize, 28, DIM)

    def _draw_menu(self):
        t = self.pulse
        scale = 1.0 + 0.06 * math.sin(t * 2.2)
        fsize = int(108 * scale)
        title = "NEÓN ESQUIVA".encode("utf-8")
        wtext = rl.MeasureText(title, fsize)
        x = (W - wtext) // 2

        rl.BeginBlendMode(rl.BLEND_ADDITIVE)
        rl.DrawText(title, x, 350, fsize, (CYAN[0], CYAN[1], CYAN[2], 80))
        rl.DrawText(title, x + 3, 353, fsize, (CYAN[0], CYAN[1], CYAN[2], 60))
        rl.EndBlendMode()
        rl.DrawText(title, x, 350, fsize, WHITE)

        self._center("ESQUIVA TODO. SOBREVIVE.".encode("utf-8"), 520, 34, DIM)
        self._center("PULSA ESPACIO PARA JUGAR".encode("utf-8"), 640, 46, GOLD)
        self._center("IZQUIERDA / DERECHA  o  A / D  para moverte".encode("utf-8"), 760, 30, WHITE)
        self._center("RATÓN para moverte".encode("utf-8"), 802, 30, WHITE)
        self._center("R = reiniciar    ESC = salir".encode("utf-8"), 862, 26, DIM)

    def _draw_game_over(self):
        rl.BeginBlendMode(rl.BLEND_ADDITIVE)
        self._center("FIN DEL JUEGO".encode("utf-8"), 380, 100, (RED_N[0], RED_N[1], RED_N[2], 70))
        rl.EndBlendMode()
        self._center("FIN DEL JUEGO".encode("utf-8"), 380, 100, RED_N)

        score_text = ("PUNTOS %d" % int(self.score)).encode("utf-8")
        self._center(score_text, 520, 56, WHITE)
        best_text = ("RÉCORD %d" % best_score).encode("utf-8")
        self._center(best_text, 590, 38, GOLD)

        if self.dead_timer >= 0.6:
            self._center("ESPACIO PARA REINTENTAR".encode("utf-8"), 700, 34, WHITE)
            self._center("R = reiniciar".encode("utf-8"), 750, 26, DIM)

    def _draw_popups(self):
        for p in self.popups:
            k = p["life"] / p["maxlife"]
            a = int(255 * k)
            size = int(p["size"] * (1.0 + (1.0 - k) * 0.3))
            wtext = rl.MeasureText(p["text"], size)
            c = p["color"]
            rl.DrawText(
                p["text"], int(p["x"] - wtext / 2), int(p["y"]),
                size, (c[0], c[1], c[2], a),
            )


def _autopilot_dodge(game):
    best = None
    best_y = -1e9
    for o in game.obstacles:
        if not o["passed"] and o["y"] < game.py + PLAYER_R:
            if o["y"] > best_y:
                best_y = o["y"]
                best = o
    if best is None:
        return {}
    return {"left": True} if best["x"] >= game.px else {"right": True}


def simulate(ticks):
    rl.SetRandomSeed(0)
    game = Game()
    for i in range(ticks):
        dt = 1.0 / 60.0
        inp = {}
        if i == 0:
            inp["space_pressed"] = True
        elif game.state == PLAYING:
            inp = _autopilot_dodge(game)
        elif game.state == GAME_OVER:
            if i % 45 == 0:
                inp["space_pressed"] = True
        game.update(dt, inp)

    print("--- SIMULATE (%d ticks) ---" % ticks)
    print("estado final:", game.state)
    print("score:", int(game.score))
    print("obstaculos generados:", game.obstacles_spawned)
    print("particulas vivas:", len(game.particles))
    print("game over:", game.died)
    print("near misses:", game.near_misses)
    print("dificultad:", round(game.difficulty, 3))
    print("-----------------------------")


def read_inputs(last_mouse_x, mouse_scale=1.0):
    inp = {
        "left": rl.IsKeyDown(rl.KEY_LEFT) or rl.IsKeyDown(rl.KEY_A),
        "right": rl.IsKeyDown(rl.KEY_RIGHT) or rl.IsKeyDown(rl.KEY_D),
        "space_pressed": rl.IsKeyPressed(rl.KEY_SPACE),
        "enter_pressed": rl.IsKeyPressed(rl.KEY_ENTER),
        "r_pressed": rl.IsKeyPressed(rl.KEY_R),
    }
    mx = rl.GetMouseX()
    inp["mouse_x"] = mx * mouse_scale
    inp["mouse_moved"] = abs(mx - last_mouse_x) > 1.0
    return inp, mx


def play_queued_sounds(game, sounds):
    if not sounds or not game.sound_queue:
        game.sound_queue.clear()
        return
    for name in game.sound_queue:
        s = sounds.get(name)
        if s is not None:
            rl.PlaySound(s)
    game.sound_queue.clear()


def main():
    args = sys.argv[1:]

    if "--simulate" in args:
        try:
            idx = args.index("--simulate")
            ticks = int(args[idx + 1]) if idx + 1 < len(args) else 900
        except (ValueError, IndexError):
            ticks = 900
        simulate(ticks)
        return

    self_test = "--self-test" in args

    rl.SetConfigFlags(rl.FLAG_WINDOW_HIDDEN)
    rl.InitWindow(W, H, "NEÓN ESQUIVA".encode("utf-8"))
    mon = rl.GetCurrentMonitor()
    mw = rl.GetMonitorWidth(mon)
    mh = rl.GetMonitorHeight(mon)
    view_h = max(320, min(mh - FIT_MARGIN, H))
    view_w = int(round(view_h * W / H))
    rl.SetWindowSize(view_w, view_h)
    rl.SetWindowPosition((mw - view_w) // 2, (mh - view_h) // 2)
    rl.ClearWindowState(rl.FLAG_WINDOW_HIDDEN)
    rl.SetTargetFPS(60)
    if self_test:
        rl.SetRandomSeed(12345)
    else:
        rl.SetRandomSeed(int(time.time() * 1000) & 0x7FFFFFFF)

    render_tex = rl.LoadRenderTexture(W, H)
    mouse_scale = W / float(view_w)

    sounds, tmpdir = init_audio()
    game = Game()
    last_mouse_x = rl.GetMouseX()
    frames = 0

    while not rl.WindowShouldClose():
        dt = rl.GetFrameTime()
        if dt <= 0.0 or dt > 0.1:
            dt = 1.0 / 60.0

        inp, last_mouse_x = read_inputs(last_mouse_x, mouse_scale)

        if self_test:
            inp["space_pressed"] = (frames == 5) or inp["space_pressed"]
            if frames > 5:
                inp["right"] = True
                inp["left"] = False

        game.update(dt, inp)
        play_queued_sounds(game, sounds)

        rl.BeginTextureMode(render_tex)
        rl.ClearBackground(game.current_bg())
        game.draw()
        rl.EndTextureMode()

        rl.BeginDrawing()
        rl.ClearBackground((4, 3, 10, 255))
        rl.DrawTexturePro(
            render_tex.texture,
            (0.0, 0.0, float(W), float(-H)),
            (0.0, 0.0, float(view_w), float(view_h)),
            (0.0, 0.0), 0.0, WHITE,
        )
        rl.EndDrawing()

        if self_test:
            frames += 1
            if frames == 120:
                rl.TakeScreenshot(b"zz_selftest.png")
            if frames >= 130:
                break

    rl.UnloadRenderTexture(render_tex)
    rl.CloseWindow()
    cleanup_audio(sounds, tmpdir)

    if self_test:
        print("SELFTEST OK")


if __name__ == "__main__":
    main()