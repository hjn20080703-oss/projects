"""
Platformer Game
"""
import arcade

# Constants
SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 650
SCREEN_TITLE = "Platformer"

# Constants used to scale our sprites from their original size
CHARACTER_SCALING = 1
TILE_SCALING = 0.5
# Movement speed of player, in pixels per frame
PLAYER_MOVEMENT_SPEED = 5
GRAVITY = 1
PLAYER_JUMP_SPEED = 20

VIEWPORT_MARGIN = 200
CAMERA_SPEED = 0.1

# Player starting position
PLAYER_START_X = 64
PLAYER_START_Y = 225
CHAOSSTONE_SCALING = 0.5

LAYER_NAME_SOUTHERNFRONTIER = "southern frontier"
LAYER_NAME_NORTHERNPLAIN = "nouthern plain"
LAYER_NAME_WESTERNDESERT = "western desert"
LAYER_NAME_EASTERNSEA = "eastern sea"
LAYER_NAME_DREAMREALM = "dream realm"
LAYER_NAME_HEAVENCOURT = "heaven court"
class MyGame(arcade.Window):
    """
    Main application class.
    """

    def __init__(self):

        # Call the parent class and set up the window
        super().__init__(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)
        self.scene = None
        self.wall_list = None
        self.player_list = None  
        self.player_sprite = None

        arcade.set_background_color(arcade.csscolor.CORNFLOWER_BLUE)
        self.camera_sprites = arcade.Camera(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.camera_gui = arcade.Camera(SCREEN_WIDTH, SCREEN_HEIGHT)        

    def setup(self):
        """Set up the game here. Call this function to restart the game."""
        # Initialize Scene
        self.scene = arcade.Scene()

        # Create the Sprite lists
        self.scene.add_sprite_list("Player")
        self.scene.add_sprite_list("Walls", use_spatial_hash=True)
        
        self.player_list = arcade.SpriteList()
        self.wall_list = arcade.SpriteList(use_spatial_hash=True)

        # Set up the player, specifically placing it at these coordinates.
        image_source = "character.png"
        self.player_sprite = arcade.AnimatedTimeBasedSprite(scale=0.7)
        self.player_sprite.frames = []
        self.player_sprite.center_x = 256
        self.player_sprite.center_y = 512
        self.player_list.append(self.player_sprite)
        # Idle RIGHT
        idle_right_tex = arcade.load_texture("character.png", x=0, y=96, width=32, height=32)
        self.idle_right = arcade.AnimationKeyframe(0, 250, idle_right_tex)
        # Idle LEFT
        idle_left_tex = arcade.load_texture("character.png", x=0, y=64, width=32, height=32)
        self.idle_left = arcade.AnimationKeyframe(0, 250, idle_left_tex)        
        self.player_sprite.texture = idle_right_tex
        self.player_sprite.frames.append(self.idle_right)        
        self.walk_right_frames = []
        for i in range(4):
            tex = arcade.load_texture("character.png", x=i * 32, y=96, width=32, height=32)
            frame = arcade.AnimationKeyframe(i, 150, tex)
            self.walk_right_frames.append(frame)
        self.walk_left_frames = []
        for i in range(4):
            tex = arcade.load_texture("character.png", x=i * 32, y=64, width=32, height=32)
            frame = arcade.AnimationKeyframe(i, 150, tex)
            self.walk_left_frames.append(frame)
        self.scene.add_sprite("Player", self.player_sprite)

        # Create the ground
        # This shows using a loop to place multiple sprites horizontally
        for x in range(0, 1250, 64):
            wall = arcade.Sprite("clouds.png", TILE_SCALING)
            wall.center_x = x
            wall.center_y = 32
            self.scene.add_sprite("Walls", wall)
            self.wall_list.append(wall)

        # Put some crates on the ground
        # This shows using a coordinate list to place sprites
        coordinate_list = [[512, 96], [256, 96], [768, 96]]

        for coordinate in coordinate_list:
            # Add a crate on the ground
            wall = arcade.Sprite(
                "character.png", TILE_SCALING
            )
            wall.position = coordinate
            self.wall_list.append(wall)
            self.scene.add_sprite("Walls", wall)
            # Create the 'physics engine'
        self.physics_engine = arcade.PhysicsEngineSimple(
            self.player_sprite, self.scene.get_sprite_list("Walls")
        )          
        self.view_left = 0
        self.view_bottom = 0             

    def on_draw(self):
        """Render the screen."""

        self.clear()
        self.camera_sprites.use()
        self.scene.draw()
        self.camera_gui.use()
        left_boundary = VIEWPORT_MARGIN
        right_boundary = self.width - VIEWPORT_MARGIN
        top_boundary = self.height - VIEWPORT_MARGIN
        bottom_boundary = VIEWPORT_MARGIN        
    def on_key_press(self, key, modifiers):
        """Called whenever a key is pressed."""

        if key == arcade.key.UP or key == arcade.key.W:
            self.player_sprite.change_y = PLAYER_MOVEMENT_SPEED
        elif key == arcade.key.DOWN or key == arcade.key.S:
            self.player_sprite.change_y = -PLAYER_MOVEMENT_SPEED
        elif key == arcade.key.LEFT or key == arcade.key.A:
            self.player_sprite.change_x = -PLAYER_MOVEMENT_SPEED
        elif key == arcade.key.RIGHT or key == arcade.key.D:
            self.player_sprite.change_x = PLAYER_MOVEMENT_SPEED
        elif key == arcade.key.SPACE:
            self.player_sprite.change_y = PLAYER_JUMP_SPEED           
    def on_key_release(self, key, modifiers):
        """Called when the user releases a key."""

        if key == arcade.key.UP or key == arcade.key.W:
            self.player_sprite.change_y = 0
        elif key == arcade.key.DOWN or key == arcade.key.S:
            self.player_sprite.change_y = 0
        elif key == arcade.key.LEFT or key == arcade.key.A:
            self.player_sprite.change_x = 0
        elif key == arcade.key.RIGHT or key == arcade.key.D:
            self.player_sprite.change_x = 0   
    def on_update(self, delta_time):
        """Movement and game logic"""

        # Move the player with the physics engine
        self.physics_engine.update()
        self.scroll_to_player()    
    def scroll_to_player(self):

        # Scroll left
        left_boundary = self.view_left + VIEWPORT_MARGIN
        if self.player_sprite.left < left_boundary:
            self.view_left -= left_boundary - self.player_sprite.left

        # Scroll right
        right_boundary = self.view_left + self.width - VIEWPORT_MARGIN
        if self.player_sprite.right > right_boundary:
            self.view_left += self.player_sprite.right - right_boundary

        # Scroll up
        top_boundary = self.view_bottom + self.height - VIEWPORT_MARGIN
        if self.player_sprite.top > top_boundary:
            self.view_bottom += self.player_sprite.top - top_boundary

        # Scroll down
        bottom_boundary = self.view_bottom + VIEWPORT_MARGIN
        if self.player_sprite.bottom < bottom_boundary:
            self.view_bottom -= bottom_boundary - self.player_sprite.bottom

        # Scroll to the proper location
        position = self.view_left, self.view_bottom
        self.camera_sprites.move_to(position, CAMERA_SPEED)

    def on_resize(self, width, height):
        """
        Resize window
        Handle the user grabbing the edge and resizing the window.
        """
        self.camera_sprites.resize(int(width), int(height))
        self.camera_gui.resize(int(width), int(height))    

def main():
    """Main function"""
    window = MyGame()
    window.setup()
    arcade.run()


if __name__ == "__main__":
    main()