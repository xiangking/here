import yaml

class CharacterConfig:
    def __init__(
        self,
        name,
        color,
        sprite_prefix,
        sprites=[],
        emotion_tags="",
        sprite_scale=1.0,
        character_setting="",
        character_profile=None,
        visual_reference_image="",
        visual_identity="",
        speech_speed=1.0,
        speech_volume=1.0,
        pronunciation_map=None,
    ):
        # 角色基本信息  
        self.name = name
        self.color = color
        self.sprite_prefix = sprite_prefix
        self.sprites = sprites
        self.character_setting = character_setting
        self.character_profile = character_profile or {}
        self.visual_reference_image = visual_reference_image
        self.visual_identity = visual_identity
        self.sprite_scale = sprite_scale
        self.emotion_tags = emotion_tags
        self.speech_speed = speech_speed
        self.speech_volume = speech_volume
        self.pronunciation_map = pronunciation_map or {}

    @staticmethod
    def read_from_files(path):
        """
        从YAML文件中读取角色配置并返回CharacterConfig对象列表。
        
        Args:
            path (str): YAML配置文件的路径
            
        Returns:
            list[CharacterConfig]: 包含所有角色配置的列表
        """
        with open(path, 'r', encoding='utf-8') as file:
            config_data = yaml.safe_load(file)
        
        characters = []
        for char_data in config_data:
            # 确保必需的字段存在
            if not all(key in char_data for key in ['name', 'color', 'sprite_prefix']):
                raise ValueError("YAML配置缺少必需字段（name, color, sprite_prefix）")
            
            # 创建CharacterConfig对象
            character=CharacterConfig.parse_dic(char_data=char_data)
            characters.append(character)
        return characters
    
    @staticmethod
    def parse_dic(char_data):
        character = CharacterConfig(
                name=char_data['name'],
                color=char_data['color'],
                sprite_prefix=char_data['sprite_prefix'],
                sprites=char_data.get("sprites"),
                sprite_scale=char_data.get("sprite_scale",1.0),
                emotion_tags=char_data.get("emotion_tags",""),
                character_setting=char_data.get("character_setting",""),
                character_profile=char_data.get("character_profile") or {},
                visual_reference_image=char_data.get("visual_reference_image", ""),
                visual_identity=char_data.get("visual_identity", ""),
                speech_speed=char_data.get("speech_speed", 1.0),
                speech_volume=char_data.get("speech_volume", 1.0),
                pronunciation_map=char_data.get("pronunciation_map") or {},
            )
        return character
