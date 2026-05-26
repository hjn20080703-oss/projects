"""
FATE WAR — top-down adventure with Tiled maps.
"""
import json
import math
import os
from pathlib import Path

import arcade
import pytiled_parser
from pyglet.math import Vec2

# --- Display ---
SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 650
SCREEN_TITLE = "FATE WAR"
FULLSCREEN = True

# --- Camera ---
VIEWPORT_MARGIN = 200
CAMERA_SPEED = 0.1
WORLD_VIEWPORT_WIDTH = 256
WORLD_VIEWPORT_HEIGHT = 192

# --- Movement ---
TILE_SIZE = 32
PLAYER_MOVEMENT_SPEED = 4
PLAYER_SCALE = 1.0
JUMP_TILES = 2
JUMP_DISTANCE = TILE_SIZE * JUMP_TILES
JUMP_DURATION = 0.22
JUMP_VISUAL_LIFT = 12
NUM_LEVELS = 5
WALK_FRAME_DURATION = 0.15
ENEMY_IMAGE = "nobody.png"
ENEMY_SCALE = 1.0
ENEMY_SPEED = 2.5
ENEMY_DETECTION_RANGE = 240
ENEMY_SPAWN_COUNT = 3
# Hidden-in-bush: keep the player faintly visible to the user,
# while enemies treat the player as not detectable.
STEALTH_ALPHA = 90

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SPRITE_SHEET = "mc and some materials.png"
SPRITE_FRAME = 32

# Tiled maps (level 1 = your tilemap from Tiled Editor)
LEVEL_MAP_FILES = {
    1: "level1.json",
    2: "level2.json",
    3: "level3.json",
    4: "level4.json",
    5: "level5.json",
    6: "level6.json",
}
DEFAULT_LEVEL_MAP = "level1.json"
TILED_TILESET_FILE = "tilset1.json"
SAVE_FILE = "savegame.json"
SAVE_SLOTS = 3

MENU_ITEMS = ("Start", "Continue", "Leave")

# Tile images that block movement (from tilset1.json)
BLOCKING_TILE_IMAGES = {"Bush.png", "Mountain.png"}

# 4x4 sheet: row 0=down, 1=up, 2=left, 3=right (y measured from top of PNG)
DIRECTION_ROWS = {
    "down": 0,
    "up": 32,
    "left": 64,
    "right": 96,
}

# Forward leap offset (Pokemon-style hop in facing direction)
DIRECTION_DELTA = {
    "up": (0, JUMP_DISTANCE),
    "down": (0, -JUMP_DISTANCE),
    "left": (-JUMP_DISTANCE, 0),
    "right": (JUMP_DISTANCE, 0),
}

# Menu colors
COLOR_BG_TOP = (18, 12, 42)
COLOR_BG_BOTTOM = (8, 20, 48)
COLOR_PANEL = (30, 22, 58, 220)
COLOR_GOLD = (255, 210, 80)
COLOR_GOLD_DIM = (180, 140, 50)
COLOR_TEXT = (245, 240, 255)
COLOR_TEXT_DIM = (160, 155, 190)

def load_character_textures():
    """Load walk cycle (4 frames) per direction from the 4x4 spritesheet."""
    walk = {}
    idle = {}
    for direction, row_y in DIRECTION_ROWS.items():
        frames = []
        for col in range(4):
            frames.append(
                arcade.load_texture(
                    SPRITE_SHEET,
                    x=col * SPRITE_FRAME,
                    y=row_y,
                    width=SPRITE_FRAME,
                    height=SPRITE_FRAME,
                )
            )
        walk[direction] = frames
        idle[direction] = frames[0]
    return walk, idle


CHAR_WALK_TEXTURES, CHAR_IDLE_TEXTURES = load_character_textures()


def save_file_path(slot: int | None = None):
    """
    Save slot files live next to the game script.
    - slot=None keeps legacy path `savegame.json`
    - slot=1..SAVE_SLOTS uses `savegame_slot{slot}.json`
    """
    if slot is None:
        return Path(SCRIPT_DIR) / SAVE_FILE
    return Path(SCRIPT_DIR) / f"savegame_slot{int(slot)}.json"


def has_save_data(slot: int | None = None):
    if slot is None:
        return save_file_path().is_file()
    return save_file_path(slot).is_file()


def save_game(level, player_x, player_y, facing, map_file, slot: int = 1):
    data = {
        "level": level,
        "player_x": player_x,
        "player_y": player_y,
        "facing": facing,
        "map_file": map_file,
    }
    with save_file_path(slot).open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_save_data(slot: int = 1):
    """
    Load save data from a given slot.
    Also supports legacy `savegame.json` by treating it as slot 1 if the new file doesn't exist yet.
    """
    path = save_file_path(slot)
    if not path.is_file() and int(slot) == 1:
        legacy = save_file_path()
        if legacy.is_file():
            path = legacy
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def any_slot_has_save_data():
    if has_save_data():
        return True
    for i in range(1, SAVE_SLOTS + 1):
        if has_save_data(i):
            return True
    return False


def slot_summary(slot: int):
    data = load_save_data(slot)
    if not data:
        return None
    level = int(data.get("level", 1))
    map_file = data.get("map_file", DEFAULT_LEVEL_MAP)
    return {"level": level, "map_file": map_file}


def build_tile_catalog(tiled_map):
    """Map global tile id -> image filename from Tiled tilesets (tilset1.json)."""
    catalog = {}
    for tileset in tiled_map.tilesets.values():
        for local_id, tile in tileset.tiles.items():
            gid = tileset.firstgid + local_id
            image_ref = tile.image
            image_path = image_ref.path if hasattr(image_ref, "path") else image_ref
            catalog[gid] = os.path.basename(str(image_path))
    return catalog


def _flatten_chunk_data(chunk_data, width, height):
    """Tiled chunk data may be a flat list or a list of row lists."""
    if not chunk_data:
        return []
    if isinstance(chunk_data[0], list):
        flat = []
        for row in chunk_data:
            flat.extend(row)
        return flat
    return chunk_data


def parse_tiled_layer_grid(layer_json):
    """
    Read one tile layer from level1.json (supports infinite chunk maps).
    Uses the exported JSON exactly as Tiled wrote it.
    """
    grid = {}
    start_x = layer_json.get("startx", 0) + layer_json.get("x", 0)
    start_y = layer_json.get("starty", 0) + layer_json.get("y", 0)

    chunks = layer_json.get("chunks")
    if chunks:
        for chunk in chunks:
            cw, ch = chunk["width"], chunk["height"]
            ox, oy = chunk["x"], chunk["y"]
            flat = _flatten_chunk_data(chunk["data"], cw, ch)
            for idx, gid in enumerate(flat):
                if gid == 0:
                    continue
                lx, ly = idx % cw, idx // cw
                grid[(start_x + ox + lx, start_y + oy + ly)] = gid
    elif layer_json.get("data"):
        w, h = layer_json["width"], layer_json["height"]
        flat = _flatten_chunk_data(layer_json["data"], w, h)
        for idx, gid in enumerate(flat):
            if gid == 0:
                continue
            lx, ly = idx % w, idx // w
            grid[(start_x + lx, start_y + ly)] = gid
    return grid


def tile_to_pixel(tx, ty, min_tx, max_ty, tile_size):
    px = (tx - min_tx) * tile_size + tile_size / 2
    py = (max_ty - ty) * tile_size + tile_size / 2
    return px, py


def make_map_sprite(image_file, px, py, tile_size):
    sprite = arcade.Sprite(image_file, 1.0, center_x=px, center_y=py)
    if image_file == "Mountain.png":
        sprite.bottom = py - tile_size / 2
    return sprite


def load_tiled_map(map_filename, fallback_w, fallback_h, level_number: int = 1):
    """
    Load a Tiled JSON map (e.g. level1.json) exactly as exported from Tiled Editor.
    """
    map_path = Path(SCRIPT_DIR) / map_filename
    if not map_path.is_file():
        raise FileNotFoundError(map_path)

    with map_path.open(encoding="utf-8") as f:
        raw_map = json.load(f)

    tiled_map = pytiled_parser.parse_map(map_path)
    tile_size = tiled_map.tile_size.width
    tile_catalog = build_tile_catalog(tiled_map)

    # Layer order and startx/starty come straight from level1.json
    tile_layers_json = [
        layer
        for layer in raw_map.get("layers", [])
        if layer.get("type") == "tilelayer" and layer.get("visible", True)
    ]

    if not tile_layers_json:
        raise ValueError(f"No tile layers found in {map_filename}")

    print(
        f"Loading Tiled map: {map_filename} "
        f"({len(tile_catalog)} tiles, {len(tile_layers_json)} layers, "
        f"tileset {TILED_TILESET_FILE})"
    )

    all_tiles = {}
    for layer_json in tile_layers_json:
        all_tiles.update(parse_tiled_layer_grid(layer_json))

    min_tx = min(x for x, _ in all_tiles)
    max_tx = max(x for x, _ in all_tiles)
    min_ty = min(y for _, y in all_tiles)
    max_ty = max(y for _, y in all_tiles)

    map_pixel_w = (max_tx - min_tx + 1) * tile_size
    map_pixel_h = (max_ty - min_ty + 1) * tile_size

    floor_list = arcade.SpriteList()
    bush_list = arcade.SpriteList()
    mountain_list = arcade.SpriteList()
    wall_list = arcade.SpriteList(use_spatial_hash=True)
    walkable_grass = []

    for layer_json in tile_layers_json:
        layer_name = (layer_json.get("name") or "").lower()
        is_mountain_layer = layer_name == "mountain"
        grid = parse_tiled_layer_grid(layer_json)

        for (tx, ty), gid in grid.items():
            image_file = tile_catalog.get(gid)
            if not image_file:
                continue

            is_bush = image_file == "Bush.png"
            is_mountain = image_file == "Mountain.png"
            is_blocking_tile = image_file in BLOCKING_TILE_IMAGES
            px, py = tile_to_pixel(tx, ty, min_tx, max_ty, tile_size)

            if is_mountain_layer:
                if is_mountain:
                    mountain_list.append(make_map_sprite(image_file, px, py, tile_size))
                    hitbox = arcade.Sprite(
                        "Grass.png", 0.01, center_x=px, center_y=py
                    )
                    hitbox.alpha = 0
                    wall_list.append(hitbox)
                elif is_blocking_tile and not (level_number == 1 and is_bush):
                    sprite = make_map_sprite(image_file, px, py, tile_size)
                    mountain_list.append(sprite)
                    wall_list.append(sprite)
                else:
                    floor_list.append(make_map_sprite(image_file, px, py, tile_size))
                    if image_file == "Grass.png":
                        walkable_grass.append((px, py))
            elif is_bush:
                # Level 1: bushes are enterable; after entering, player can hide.
                sprite = make_map_sprite(image_file, px, py, tile_size)
                bush_list.append(sprite)
                if is_blocking_tile and level_number != 1:
                    wall_list.append(sprite)
            elif is_blocking_tile:
                # Fallback for other blocking tiles (currently expected: only Bush/Mountain).
                sprite = make_map_sprite(image_file, px, py, tile_size)
                bush_list.append(sprite)
                wall_list.append(sprite)
            else:
                floor_list.append(make_map_sprite(image_file, px, py, tile_size))
                if image_file == "Grass.png":
                    walkable_grass.append((px, py))

    if walkable_grass:
        spawn_x, spawn_y = walkable_grass[len(walkable_grass) // 2]
    else:
        spawn_x = map_pixel_w / 2
        spawn_y = map_pixel_h / 2

    return (
        floor_list,
        bush_list,
        mountain_list,
        wall_list,
        map_pixel_w,
        map_pixel_h,
        spawn_x,
        spawn_y,
        map_filename,
    )


def draw_vertical_gradient(width, height, top_rgb, bottom_rgb, steps=32):
    """Simple fullscreen gradient background."""
    step_h = height / steps
    for i in range(steps):
        t = i / max(steps - 1, 1)
        r = int(top_rgb[0] + (bottom_rgb[0] - top_rgb[0]) * t)
        g = int(top_rgb[1] + (bottom_rgb[1] - top_rgb[1]) * t)
        b = int(top_rgb[2] + (bottom_rgb[2] - top_rgb[2]) * t)
        y = height - (i + 0.5) * step_h
        arcade.draw_rectangle_filled(
            width / 2, y, width, step_h + 2, (r, g, b)
        )


def draw_menu_frame(cx, cy, panel_w, panel_h):
    """Decorative panel behind title and prompts."""
    arcade.draw_rectangle_filled(cx, cy, panel_w + 12, panel_h + 12, (10, 8, 24))
    arcade.draw_rectangle_filled(cx, cy, panel_w, panel_h, (38, 28, 72))
    arcade.draw_rectangle_outline(
        cx, cy, panel_w, panel_h, COLOR_GOLD, 3
    )
    arcade.draw_rectangle_outline(
        cx, cy, panel_w - 10, panel_h - 10, COLOR_GOLD_DIM, 1
    )


class GameWindow(arcade.Window):
    def __init__(self):
        super().__init__(
            SCREEN_WIDTH,
            SCREEN_HEIGHT,
            SCREEN_TITLE,
            fullscreen=FULLSCREEN,
            resizable=False,
        )
        os.chdir(SCRIPT_DIR)
        self.show_view(MenuView())


class MenuView(arcade.View):
    """Title screen — Start / Continue / Leave."""

    def __init__(self):
        super().__init__()
        self.title_pulse = 0.0
        self.preview_frame = 0
        self.preview_timer = 0.0
        self.preview_directions = ["down", "left", "up", "right"]
        self.preview_dir_index = 0
        self.selected_index = 0
        self.menu_hitboxes = []

    def on_show_view(self):
        arcade.set_background_color(COLOR_BG_TOP)
        self.selected_index = 0

    def on_update(self, delta_time):
        self.title_pulse += delta_time * 2.5
        self.preview_timer += delta_time
        if self.preview_timer >= 0.4:
            self.preview_timer = 0.0
            self.preview_frame = (self.preview_frame + 1) % 4
            if self.preview_frame == 0:
                self.preview_dir_index = (
                    self.preview_dir_index + 1
                ) % len(self.preview_directions)

    def _menu_layout(self, w, h):
        """Return list of (label, center_x, center_y, width, height, enabled)."""
        cx = w / 2
        base_y = h / 2 - 130
        spacing = 56
        btn_w = 320
        btn_h = 44
        items = []
        for i, label in enumerate(MENU_ITEMS):
            enabled = True
            if label == "Continue" and not any_slot_has_save_data():
                enabled = False
            items.append(
                (label, cx, base_y - i * spacing, btn_w, btn_h, enabled)
            )
        return items

    def on_draw(self):
        self.clear()
        w = self.window.width
        h = self.window.height

        draw_vertical_gradient(w, h, COLOR_BG_TOP, COLOR_BG_BOTTOM)

        margin = 40
        arcade.draw_line(margin, h - margin, w - margin, h - margin, COLOR_GOLD, 2)
        arcade.draw_line(margin, margin, w - margin, margin, COLOR_GOLD, 2)

        panel_w = min(720, w * 0.75)
        panel_h = min(480, h * 0.62)
        draw_menu_frame(w / 2, h / 2, panel_w, panel_h)

        pulse = 1.0 + 0.04 * math.sin(self.title_pulse)
        title_size = int(72 * pulse)
        arcade.draw_text(
            "FATE WAR",
            w / 2 + 3,
            h / 2 + 120,
            (0, 0, 0),
            font_size=title_size,
            anchor_x="center",
            bold=True,
        )
        arcade.draw_text(
            "FATE WAR",
            w / 2,
            h / 2 + 123,
            COLOR_GOLD,
            font_size=title_size,
            anchor_x="center",
            bold=True,
        )

        direction = self.preview_directions[self.preview_dir_index]
        preview_tex = CHAR_WALK_TEXTURES[direction][self.preview_frame]
        arcade.draw_texture_rectangle(
            w / 2,
            h / 2 + 30,
            SPRITE_FRAME * 3,
            SPRITE_FRAME * 3,
            preview_tex,
        )

        self.menu_hitboxes = []
        for i, (label, cx, cy, bw, bh, enabled) in enumerate(self._menu_layout(w, h)):
            selected = i == self.selected_index
            left = cx - bw / 2
            bottom = cy - bh / 2
            self.menu_hitboxes.append((left, bottom, bw, bh, label, enabled))

            if selected and enabled:
                arcade.draw_rectangle_filled(cx, cy, bw + 8, bh + 8, (70, 55, 110))
                arcade.draw_rectangle_outline(cx, cy, bw + 8, bh + 8, COLOR_GOLD, 3)
            elif selected and not enabled:
                arcade.draw_rectangle_outline(cx, cy, bw, bh, COLOR_TEXT_DIM, 2)
            else:
                arcade.draw_rectangle_filled(cx, cy, bw, bh, (45, 35, 75))
                arcade.draw_rectangle_outline(cx, cy, bw, bh, COLOR_GOLD_DIM, 1)

            text_color = COLOR_TEXT if enabled else COLOR_TEXT_DIM
            arcade.draw_text(
                label,
                cx,
                cy,
                text_color,
                font_size=28 if selected else 24,
                anchor_x="center",
                anchor_y="center",
                bold=selected,
            )

        arcade.draw_text(
            "Up / Down  —  Select     Enter  —  Confirm",
            w / 2,
            72,
            COLOR_TEXT_DIM,
            font_size=15,
            anchor_x="center",
        )

    def _activate_selection(self):
        label = MENU_ITEMS[self.selected_index]
        if label == "Start":
            self.window.show_view(SaveSlotsView(mode="new"))
        elif label == "Continue":
            self.window.show_view(SaveSlotsView(mode="load"))
        elif label == "Leave":
            self.window.close()

    def _select_at_mouse(self, x, y):
        for i, (left, bottom, bw, bh, label, enabled) in enumerate(self.menu_hitboxes):
            if left <= x <= left + bw and bottom <= y <= bottom + bh:
                self.selected_index = i
                if enabled:
                    self._activate_selection()
                return

    def on_key_press(self, key, modifiers):
        if key == arcade.key.UP:
            self.selected_index = (self.selected_index - 1) % len(MENU_ITEMS)
        elif key == arcade.key.DOWN:
            self.selected_index = (self.selected_index + 1) % len(MENU_ITEMS)
        elif key in (arcade.key.ENTER, arcade.key.SPACE):
            self._activate_selection()
        elif key == arcade.key.ESCAPE:
            self.window.close()

    def on_mouse_press(self, x, y, button, modifiers):
        if button == arcade.MOUSE_BUTTON_LEFT:
            self._select_at_mouse(x, y)


class GameView(arcade.View):
    """Main gameplay."""

    def __init__(self, saved_state=None, save_slot: int = 1):
        super().__init__()
        self.saved_state = saved_state
        self.save_slot = int(save_slot)
        self.current_level = 1
        self.current_map_file = DEFAULT_LEVEL_MAP
        self.floor_list = None
        self.bush_list = None
        self.mountain_list = None
        self.wall_list = None
        self.player_list = None
        self.player_sprite = None
        self.physics_engine = None

        self.map_pixel_width = 0
        self.map_pixel_height = 0
        self.view_left = 0
        self.view_bottom = 0

        self.facing = "down"
        self.walk_frame = 0
        self.walk_timer = 0.0

        self.is_jumping = False
        self.jump_timer = 0.0
        self.jump_start_x = 0.0
        self.jump_start_y = 0.0
        self.jump_target_x = 0.0
        self.jump_target_y = 0.0

        self.enemy_list = None
        self.player_hidden = False

        # Direction key "held" state (so jump won't cancel movement).
        self.hold_up = False
        self.hold_down = False
        self.hold_left = False
        self.hold_right = False
        self.input_change_x = 0
        self.input_change_y = 0

        self.camera_sprites = None
        self.camera_gui = None

    def on_show_view(self):
        arcade.set_background_color(arcade.color.DARK_GREEN)
        self._init_cameras()
        if self.saved_state:
            level = int(self.saved_state.get("level", 1))
            self.load_level(level)
            self.player_sprite.center_x = float(self.saved_state["player_x"])
            self.player_sprite.center_y = float(self.saved_state["player_y"])
            facing = self.saved_state.get("facing", "down")
            if facing in CHAR_IDLE_TEXTURES:
                self.facing = facing
                self.player_sprite.texture = CHAR_IDLE_TEXTURES[facing]
            self.saved_state = None
            self.scroll_to_player(immediate=True)
            self._update_player_stealth()
        else:
            self.load_level(self.current_level)
            self._update_player_stealth()

    def _init_cameras(self):
        w, h = self.window.width, self.window.height
        self.camera_sprites = arcade.Camera(w, h)
        self.camera_gui = arcade.Camera(w, h)
        # Keep scale at 1 — arcade's Camera.scale breaks easily; zoom via viewport below.
        self.camera_sprites.scale = 1.0

    def load_level(self, level_number):
        self.current_level = level_number
        map_file = LEVEL_MAP_FILES.get(level_number, f"level{level_number}.json")
        self.current_map_file = map_file
        fw = self.window.width
        fh = self.window.height

        try:
            (
                self.floor_list,
                self.bush_list,
                self.mountain_list,
                self.wall_list,
                self.map_pixel_width,
                self.map_pixel_height,
                spawn_x,
                spawn_y,
                self.current_map_file,
            ) = load_tiled_map(map_file, fw, fh, level_number=level_number)
        except (FileNotFoundError, ValueError) as err:
            self.floor_list = arcade.SpriteList()
            self.bush_list = arcade.SpriteList()
            self.mountain_list = arcade.SpriteList()
            self.wall_list = arcade.SpriteList(use_spatial_hash=True)
            self.map_pixel_width = fw
            self.map_pixel_height = fh
            spawn_x = fw / 2
            spawn_y = fh / 2
            print(f"Could not load Tiled map '{map_file}': {err}")

        self.player_list = arcade.SpriteList()
        self._build_player(spawn_x, spawn_y)
        self.player_list.append(self.player_sprite)

        self.physics_engine = arcade.PhysicsEngineSimple(
            self.player_sprite, self.wall_list
        )

        # Reset stealth + enemies for each level.
        self.player_hidden = False
        self.player_sprite.alpha = 255
        self.enemy_list = arcade.SpriteList()
        if self.current_level == 1:
            self._spawn_enemies_level1(spawn_x, spawn_y)

        self.view_left = 0
        self.view_bottom = 0
        self.scroll_to_player(immediate=True)

    def _build_player(self, center_x, center_y):
        self.player_sprite = arcade.Sprite(
            scale=PLAYER_SCALE,
            center_x=center_x,
            center_y=center_y,
            texture=CHAR_IDLE_TEXTURES["down"],
        )
        self.facing = "down"
        self.walk_frame = 0
        self.walk_timer = 0.0
        self.is_jumping = False
        self.player_sprite.alpha = 255

    def _recompute_input_vector(self):
        self.input_change_x = 0
        self.input_change_y = 0

        if self.hold_up and not self.hold_down:
            self.input_change_y = PLAYER_MOVEMENT_SPEED
        elif self.hold_down and not self.hold_up:
            self.input_change_y = -PLAYER_MOVEMENT_SPEED

        if self.hold_left and not self.hold_right:
            self.input_change_x = -PLAYER_MOVEMENT_SPEED
        elif self.hold_right and not self.hold_left:
            self.input_change_x = PLAYER_MOVEMENT_SPEED

    def _apply_movement_from_input(self):
        self.player_sprite.change_x = self.input_change_x
        self.player_sprite.change_y = self.input_change_y

    def _jump_destination_clear(self, target_x, target_y):
        """Return True if the landing tile does not overlap walls."""
        probe = arcade.Sprite(
            scale=PLAYER_SCALE,
            center_x=target_x,
            center_y=target_y,
            texture=CHAR_IDLE_TEXTURES[self.facing],
        )
        return len(arcade.check_for_collision_with_list(probe, self.wall_list)) == 0

    def _start_jump(self):
        """Pokemon-style leap: move forward in facing direction, land ahead."""
        if self.is_jumping:
            return

        dx, dy = DIRECTION_DELTA[self.facing]
        start_x = self.player_sprite.center_x
        start_y = self.player_sprite.center_y
        target_x = start_x + dx
        target_y = start_y + dy

        if not self._jump_destination_clear(target_x, target_y):
            return

        # Temporarily override physics movement; we will restore after landing.
        self.player_sprite.change_x = 0
        self.player_sprite.change_y = 0
        self.is_jumping = True
        self.jump_timer = 0.0
        self.jump_start_x = start_x
        self.jump_start_y = start_y
        self.jump_target_x = target_x
        self.jump_target_y = target_y

    def _update_jump(self, delta_time):
        if not self.is_jumping:
            return

        self.jump_timer += delta_time
        t = min(self.jump_timer / JUMP_DURATION, 1.0)
        # Smooth step — quick leap, no snap
        t = t * t * (3.0 - 2.0 * t)

        self.player_sprite.center_x = (
            self.jump_start_x + (self.jump_target_x - self.jump_start_x) * t
        )
        ground_y = self.jump_start_y + (self.jump_target_y - self.jump_start_y) * t
        # Small visual lift mid-air only; lands at destination (not原路回落)
        self.player_sprite.center_y = ground_y + JUMP_VISUAL_LIFT * math.sin(
            math.pi * t
        )

        if t >= 1.0:
            self.is_jumping = False
            self.player_sprite.center_x = self.jump_target_x
            self.player_sprite.center_y = self.jump_target_y
            # If you were still holding movement keys, resume walking immediately.
            self._apply_movement_from_input()

    def _update_player_stealth(self):
        """Level 1: being inside bush hides the player from enemies."""
        if self.current_level != 1 or not self.bush_list:
            if self.player_hidden:
                self.player_hidden = False
                self.player_sprite.alpha = 255
            return

        in_bush = len(arcade.check_for_collision_with_list(self.player_sprite, self.bush_list)) > 0
        if in_bush and not self.player_hidden:
            self.player_hidden = True
            self.player_sprite.alpha = STEALTH_ALPHA
        elif not in_bush and self.player_hidden:
            self.player_hidden = False
            self.player_sprite.alpha = 255

    def _spawn_enemies_level1(self, spawn_x: float, spawn_y: float):
        """Spawn a few enemies near the player's spawn point."""
        enemy_texture = ENEMY_IMAGE
        if not (Path(SCRIPT_DIR) / ENEMY_IMAGE).is_file():
            # Avoid crashing if enemy texture isn't exported to png yet.
            print(
                f"Warning: cannot locate '{ENEMY_IMAGE}' in {SCRIPT_DIR}. "
                f"Using placeholder texture 'Grass.png' for enemies."
            )
            enemy_texture = "Grass.png"

        offsets = [
            (5, 0),
            (-5, 0),
            (0, 5),
            (0, -5),
            (3, 3),
            (-3, 3),
            (3, -3),
            (-3, -3),
        ]
        enemies_spawned = 0

        for ox, oy in offsets:
            if enemies_spawned >= ENEMY_SPAWN_COUNT:
                break

            ex = spawn_x + ox * TILE_SIZE
            ey = spawn_y + oy * TILE_SIZE

            # Clamp inside map bounds.
            ex = max(0, min(ex, self.map_pixel_width))
            ey = max(0, min(ey, self.map_pixel_height))

            probe = arcade.Sprite(
                enemy_texture,
                ENEMY_SCALE,
                center_x=ex,
                center_y=ey,
            )
            # Avoid spawning inside walls or on top of the player.
            if len(arcade.check_for_collision_with_list(probe, self.wall_list)) > 0:
                continue
            if arcade.check_for_collision(probe, self.player_sprite):
                continue

            enemy = arcade.Sprite(
                enemy_texture,
                ENEMY_SCALE,
                center_x=ex,
                center_y=ey,
            )
            self.enemy_list.append(enemy)
            enemies_spawned += 1

    def _update_player_texture(self, delta_time):
        """Cycle walk frames for the current facing direction."""
        if self.is_jumping:
            # Mid hop uses frame 2 of current facing
            self.player_sprite.texture = CHAR_WALK_TEXTURES[self.facing][2]
            return

        moving = (
            self.player_sprite.change_x != 0
            or self.player_sprite.change_y != 0
        )

        if not moving:
            self.player_sprite.texture = CHAR_IDLE_TEXTURES[self.facing]
            self.walk_frame = 0
            self.walk_timer = 0.0
            return

        self.walk_timer += delta_time
        if self.walk_timer >= WALK_FRAME_DURATION:
            self.walk_timer = 0.0
            self.walk_frame = (self.walk_frame + 1) % 4

        self.player_sprite.texture = CHAR_WALK_TEXTURES[self.facing][
            self.walk_frame
        ]

    def on_draw(self):
        self.clear()
        self.camera_sprites.use()

        if self.floor_list:
            self.floor_list.draw()
        if self.bush_list:
            self.bush_list.draw()
        if self.enemy_list:
            self.enemy_list.draw()
        if self.player_list:
            self.player_list.draw()
        if self.mountain_list:
            self.mountain_list.draw()

        self.camera_gui.use()
        arcade.draw_rectangle_filled(
            0, 0, 280, 36, (0, 0, 0, 140)
        )
        arcade.draw_text(
            f"FATE WAR  |  Level {self.current_level}  |  {self.current_map_file}",
            12,
            10,
            COLOR_GOLD,
            font_size=14,
            bold=True,
        )

    def _save_progress(self):
        save_game(
            self.current_level,
            self.player_sprite.center_x,
            self.player_sprite.center_y,
            self.facing,
            self.current_map_file,
            slot=self.save_slot,
        )

    def on_key_press(self, key, modifiers):
        if key == arcade.key.ESCAPE:
            self._save_progress()
            self.window.show_view(MenuView())
            return

        if key == arcade.key.SPACE:
            self._start_jump()
            return

        if arcade.key.KEY_1 <= key <= arcade.key.KEY_1 + NUM_LEVELS - 1:
            if self.is_jumping:
                return
            new_level = key - arcade.key.KEY_1 + 1
            if new_level != self.current_level:
                self.load_level(new_level)
            return

        # Direction keys update held input even while jumping.
        if key in (arcade.key.UP, arcade.key.W):
            self.hold_up = True
            if not self.is_jumping:
                self.facing = "up"
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.hold_down = True
            if not self.is_jumping:
                self.facing = "down"
        elif key in (arcade.key.LEFT, arcade.key.A):
            self.hold_left = True
            if not self.is_jumping:
                self.facing = "left"
        elif key in (arcade.key.RIGHT, arcade.key.D):
            self.hold_right = True
            if not self.is_jumping:
                self.facing = "right"
        else:
            return

        self._recompute_input_vector()
        if not self.is_jumping:
            self._apply_movement_from_input()

    def on_key_release(self, key, modifiers):
        released = False
        if key in (arcade.key.UP, arcade.key.W):
            self.hold_up = False
            released = True
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.hold_down = False
            released = True
        elif key in (arcade.key.LEFT, arcade.key.A):
            self.hold_left = False
            released = True
        elif key in (arcade.key.RIGHT, arcade.key.D):
            self.hold_right = False
            released = True

        if not released:
            return

        self._recompute_input_vector()
        if not self.is_jumping:
            self._apply_movement_from_input()

    def on_update(self, delta_time):
        if self.is_jumping:
            self._update_jump(delta_time)
            self._update_player_texture(delta_time)
            self._update_player_stealth()
            self._update_enemies(delta_time)
            self.scroll_to_player()
            return

        # Apply held-direction input continuously (prevents "stuck" movement).
        self._recompute_input_vector()
        self._apply_movement_from_input()

        self.physics_engine.update()
        self._update_player_texture(delta_time)
        self._update_player_stealth()
        self._update_enemies(delta_time)
        self.scroll_to_player()

    def _update_enemies(self, delta_time):
        """Level 1 enemy: chase only if player is visible (not hidden in bush)."""
        if not self.enemy_list:
            return
        if self.current_level != 1:
            return

        if not self.player_sprite:
            return

        see_player = not self.player_hidden
        if not see_player:
            return

        px, py = self.player_sprite.center_x, self.player_sprite.center_y
        range2 = ENEMY_DETECTION_RANGE * ENEMY_DETECTION_RANGE

        for enemy in self.enemy_list:
            ex, ey = enemy.center_x, enemy.center_y
            dx = px - ex
            dy = py - ey
            dist2 = dx * dx + dy * dy

            if dist2 > range2 or dist2 == 0:
                continue

            dist = math.sqrt(dist2)
            ux = dx / dist
            uy = dy / dist

            old_x, old_y = ex, ey
            enemy.center_x = ex + ux * ENEMY_SPEED * delta_time
            enemy.center_y = ey + uy * ENEMY_SPEED * delta_time

            if len(arcade.check_for_collision_with_list(enemy, self.wall_list)) > 0:
                enemy.center_x, enemy.center_y = old_x, old_y

    def scroll_to_player(self, immediate=False):
        """
        Lock camera on player (player at screen center).
        Same as arcade/examples/sprite_move_scrolling.py
        """
        w, h = self.window.width, self.window.height
        target_left = self.player_sprite.center_x - w / 2
        target_bottom = self.player_sprite.center_y - h / 2

        max_view_left = max(0, self.map_pixel_width - w)
        max_view_bottom = max(0, self.map_pixel_height - h)

        self.view_left = max(0, min(target_left, max_view_left))
        self.view_bottom = max(0, min(target_bottom, max_view_bottom))

        # Always snap (speed=1): player stays centered on screen.
        self.camera_sprites.move_to(Vec2(self.view_left, self.view_bottom), 1.0)

    def on_resize(self, width, height):
        if self.camera_sprites:
            self.camera_sprites.resize(int(width), int(height))
            self.camera_sprites.scale = 1.0
        if self.camera_gui:
            self.camera_gui.resize(int(width), int(height))


class SaveSlotsView(arcade.View):
    """
    3-slot save/load screen.
    - mode="new": pick a slot to start a new game (overwrites that slot on next save)
    - mode="load": pick a slot to continue from (only enabled if slot has data)
    """

    def __init__(self, mode: str = "load"):
        super().__init__()
        self.mode = mode
        self.selected_index = 0
        self.hitboxes = []

    def on_show_view(self):
        arcade.set_background_color(COLOR_BG_TOP)
        self.selected_index = 0

    def _items(self, w, h):
        cx = w / 2
        base_y = h / 2 + 90
        spacing = 74
        bw = 560
        bh = 56
        items = []
        for i in range(1, SAVE_SLOTS + 1):
            summary = slot_summary(i)
            has_data = summary is not None
            enabled = True if self.mode == "new" else has_data
            title = f"Slot {i}"
            subtitle = (
                f"Level {summary['level']}  |  {summary['map_file']}"
                if has_data
                else "Empty"
            )
            items.append(
                {
                    "slot": i,
                    "cx": cx,
                    "cy": base_y - (i - 1) * spacing,
                    "bw": bw,
                    "bh": bh,
                    "enabled": enabled,
                    "title": title,
                    "subtitle": subtitle,
                }
            )
        return items

    def on_draw(self):
        self.clear()
        w = self.window.width
        h = self.window.height

        draw_vertical_gradient(w, h, COLOR_BG_TOP, COLOR_BG_BOTTOM)
        panel_w = min(820, w * 0.82)
        panel_h = min(520, h * 0.72)
        draw_menu_frame(w / 2, h / 2, panel_w, panel_h)

        heading = "Choose a Save Slot" if self.mode == "new" else "Continue — Choose Slot"
        arcade.draw_text(
            heading,
            w / 2,
            h / 2 + 190,
            COLOR_GOLD,
            font_size=40,
            anchor_x="center",
            bold=True,
        )
        hint = (
            "Enter — Start new game in slot   |   Esc — Back"
            if self.mode == "new"
            else "Enter — Load slot   |   Esc — Back"
        )
        arcade.draw_text(
            hint,
            w / 2,
            h / 2 - 210,
            COLOR_TEXT_DIM,
            font_size=15,
            anchor_x="center",
        )

        self.hitboxes = []
        for idx, it in enumerate(self._items(w, h)):
            selected = idx == self.selected_index
            enabled = it["enabled"]
            cx, cy, bw, bh = it["cx"], it["cy"], it["bw"], it["bh"]

            left = cx - bw / 2
            bottom = cy - bh / 2
            self.hitboxes.append((left, bottom, bw, bh, it["slot"], enabled))

            if selected and enabled:
                arcade.draw_rectangle_filled(cx, cy, bw + 10, bh + 10, (70, 55, 110))
                arcade.draw_rectangle_outline(cx, cy, bw + 10, bh + 10, COLOR_GOLD, 3)
            else:
                fill = (45, 35, 75) if enabled else (32, 28, 46)
                outline = COLOR_GOLD_DIM if enabled else COLOR_TEXT_DIM
                arcade.draw_rectangle_filled(cx, cy, bw, bh, fill)
                arcade.draw_rectangle_outline(cx, cy, bw, bh, outline, 2 if selected else 1)

            title_color = COLOR_TEXT if enabled else COLOR_TEXT_DIM
            sub_color = COLOR_TEXT_DIM if enabled else (120, 118, 135)
            arcade.draw_text(
                it["title"],
                cx - bw / 2 + 18,
                cy + 6,
                title_color,
                font_size=22,
                anchor_x="left",
                anchor_y="center",
                bold=True,
            )
            arcade.draw_text(
                it["subtitle"],
                cx - bw / 2 + 18,
                cy - 16,
                sub_color,
                font_size=14,
                anchor_x="left",
                anchor_y="center",
            )

    def _activate(self):
        slot = self.selected_index + 1
        if self.mode == "new":
            self.window.show_view(GameView(saved_state=None, save_slot=slot))
            return

        saved = load_save_data(slot)
        if saved:
            self.window.show_view(GameView(saved_state=saved, save_slot=slot))

    def _select_at_mouse(self, x, y):
        for i, (left, bottom, bw, bh, slot, enabled) in enumerate(self.hitboxes):
            if left <= x <= left + bw and bottom <= y <= bottom + bh:
                self.selected_index = i
                if enabled:
                    self._activate()
                return

    def on_key_press(self, key, modifiers):
        if key == arcade.key.UP:
            self.selected_index = (self.selected_index - 1) % SAVE_SLOTS
        elif key == arcade.key.DOWN:
            self.selected_index = (self.selected_index + 1) % SAVE_SLOTS
        elif key in (arcade.key.ENTER, arcade.key.SPACE):
            enabled = self._items(self.window.width, self.window.height)[self.selected_index][
                "enabled"
            ]
            if enabled:
                self._activate()
        elif key == arcade.key.ESCAPE:
            self.window.show_view(MenuView())

    def on_mouse_press(self, x, y, button, modifiers):
        if button == arcade.MOUSE_BUTTON_LEFT:
            self._select_at_mouse(x, y)


def main():
    window = GameWindow()
    arcade.run()


if __name__ == "__main__":
    main()
