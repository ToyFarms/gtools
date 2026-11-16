#version 450 core

// CyBot robot / projectile sprite (npc1.rttex), 3D pass.
layout (location = 0) in vec2 in_pos;         // quad: -0.5..0.5
layout (location = 1) in vec2 in_texCoord;    // quad: 0..1

layout (location = 2) in vec2 in_worldPos;    // instance: sprite centre, world px
layout (location = 3) in vec2 in_frameUV;     // instance: frame top-left, normalized
layout (location = 4) in float in_flip;       // instance: -1 = mirrored (left)
layout (location = 5) in float in_alpha;      // instance: 1.0 armed / 0.5 unarmed
layout (location = 6) in float in_angle;      // instance: degrees (projectiles: -90 up / 90 down)

out vec2 v_uv;
out float v_alpha;

uniform mat4 u_view_proj;
uniform sampler2DArray u_texture;
uniform float u_spriteSize;
uniform float u_depth;
uniform float u_layer_spread;

void main() {
    vec2 texSize = textureSize(u_texture, 0).xy;
    vec2 uvStep = vec2(u_spriteSize / texSize.x, u_spriteSize / texSize.y);

    float u = mix(in_texCoord.x, 1.0 - in_texCoord.x, step(in_flip, 0.0));
    v_uv = in_frameUV + vec2(u * uvStep.x, in_texCoord.y * uvStep.y);
    v_alpha = in_alpha;

    float c = cos(radians(in_angle));
    float s = sin(radians(in_angle));
    vec2 quad = vec2(in_pos.x * c - in_pos.y * s, in_pos.x * s + in_pos.y * c);

    vec2 world = quad * u_spriteSize + in_worldPos;
    gl_Position = u_view_proj * vec4(world.x, world.y, u_depth * u_layer_spread, 1.0);
}
