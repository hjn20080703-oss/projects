"""
FATE WAR — top-down adventure with Tiled maps.
"""
import json
import math
import os
from pathlib import Path

import arcade
import pytiled_parser

# --- Display ---
SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 650
SCREEN_TITLE = "FATE WAR"
FULLSCREEN = True

# --- Camera ---
VIEWPORT_MARGIN = 200
CAMERA_SPEED = 0.1

# --- Movement ---
TILE_SIZE = 32
PLAYER_MOVEMENT_SPEED = 4
PLAYER_SCALE = 1.0
JUMP_TILES = 2
JUMP_DISTANCE = TILE_SIZE * JUMP_TILES
JUMP_DURATION = 0.22
JUMP_VISUAL_LIFT = 12
NUM_LEVELS = 6
WALK_FRAME_DURATION = 0.15

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


def save_file_path():
    return Path(SCRIPT_DIR) / SAVE_FILE


def has_save_data():
    return save_file_path().is_file()


def save_game(level, player_x, player_y, facing, map_file):
    data = {
        "level": level,
        "player_x": player_x,
        "player_y": player_y,
        "facing": facing,
        "map_file": map_file,
    }
    with save_file_path().open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_save_data():
    path = save_file_path()
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


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


def load_tiled_map(map_filename, fallback_w, fallback_h):
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

            blocks = image_file in BLOCKING_TILE_IMAGES
            px, py = tile_to_pixel(tx, ty, min_tx, max_ty, tile_size)

            if is_mountain_layer:
                if image_file == "Mountain.png":
                    mountain_list.append(make_map_sprite(image_file, px, py, tile_size))
                    hitbox = arcade.Sprite(
                        "Grass.png", 0.01, center_x=px, center_y=py
                    )
                    hitbox.alpha = 0
                    wall_list.append(hitbox)
                elif blocks:
                    sprite = make_map_sprite(image_file, px, py, tile_size)
                    mountain_list.append(sprite)
                    wall_list.append(sprite)
                else:
                    floor_list.append(make_map_sprite(image_file, px, py, tile_size))
                    if image_file == "Grass.png":
                        walkable_grass.append((px, py))
            elif blocks:
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
            if label == "Continue" and not has_save_data():
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
            self.window.show_view(GameView())
        elif label == "Continue":
            saved = load_save_data()
            if saved:
                self.window.show_view(GameView(saved_state=saved))
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

    def __init__(self, saved_state=None):
        super().__init__()
        self.saved_state = saved_state
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
        else:
            self.load_level(self.current_level)

    def _init_cameras(self):
        w, h = self.window.width, self.window.height
        self.camera_sprites = arcade.Camera(w, h)
        self.camera_gui = arcade.Camera(w, h)

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
            ) = load_tiled_map(map_file, fw, fh)
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
        )

    def on_key_press(self, key, modifiers):
        if key == arcade.key.ESCAPE:
            self._save_progress()
            self.window.show_view(MenuView())
            return

        if key == arcade.key.SPACE:
            self._start_jump()
            return

        if self.is_jumping:
            return

        if arcade.key.KEY_1 <= key <= arcade.key.KEY_1 + NUM_LEVELS - 1:
            new_level = key - arcade.key.KEY_1 + 1
            if new_level != self.current_level:
                self.load_level(new_level)
            return

        if key in (arcade.key.UP, arcade.key.W):
            self.facing = "up"
            self.player_sprite.change_y = PLAYER_MOVEMENT_SPEED
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.facing = "down"
            self.player_sprite.change_y = -PLAYER_MOVEMENT_SPEED
        elif key in (arcade.key.LEFT, arcade.key.A):
            self.facing = "left"
            self.player_sprite.change_x = -PLAYER_MOVEMENT_SPEED
        elif key in (arcade.key.RIGHT, arcade.key.D):
            self.facing = "right"
            self.player_sprite.change_x = PLAYER_MOVEMENT_SPEED

    def on_key_release(self, key, modifiers):
        if key in (arcade.key.UP, arcade.key.W):
            self.player_sprite.change_y = 0
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.player_sprite.change_y = 0
        elif key in (arcade.key.LEFT, arcade.key.A):
            self.player_sprite.change_x = 0
        elif key in (arcade.key.RIGHT, arcade.key.D):
            self.player_sprite.change_x = 0

    def on_update(self, delta_time):
        if self.is_jumping:
            self._update_jump(delta_time)
            self._update_player_texture(delta_time)
            self.scroll_to_player()
            return

        self.physics_engine.update()
        self._update_player_texture(delta_time)
        self.scroll_to_player()

    def scroll_to_player(self, immediate=False):
        left_boundary = self.view_left + VIEWPORT_MARGIN
        if self.player_sprite.left < left_boundary:
            self.view_left -= left_boundary - self.player_sprite.left

        right_boundary = self.view_left + self.window.width - VIEWPORT_MARGIN
        if self.player_sprite.right > right_boundary:
            self.view_left += self.player_sprite.right - right_boundary

        top_boundary = self.view_bottom + self.window.height - VIEWPORT_MARGIN
        if self.player_sprite.top > top_boundary:
            self.view_bottom += self.player_sprite.top - top_boundary

        bottom_boundary = self.view_bottom + VIEWPORT_MARGIN
        if self.player_sprite.bottom < bottom_boundary:
            self.view_bottom -= bottom_boundary - self.player_sprite.bottom

        max_view_left = max(0, self.map_pixel_width - self.window.width)
        max_view_bottom = max(0, self.map_pixel_height - self.window.height)
        self.view_left = max(0, min(self.view_left, max_view_left))
        self.view_bottom = max(0, min(self.view_bottom, max_view_bottom))

        position = (self.view_left, self.view_bottom)
        if immediate:
            self.camera_sprites.move_to(position)
        else:
            self.camera_sprites.move_to(position, CAMERA_SPEED)

    def on_resize(self, width, height):
        if self.camera_sprites:
            self.camera_sprites.resize(int(width), int(height))
        if self.camera_gui:
            self.camera_gui.resize(int(width), int(height))


def main():
    window = GameWindow()
    arcade.run()


if __name__ == "__main__":
    main()
