#version 450 core

// Blast trail particle (particles.rttex / particles2.rttex), 3D pass.
layout (location = 0) in vec2 in_pos;         // quad: -0.5..0.5
layout (location = 1) in vec2 in_texCoord;    // quad: 0..1

layout (location = 2) in vec2 in_worldPos;    // instance: particle centre, world px
layout (location = 3) in vec2 in_frameUV;     // instance: cell top-left, normalized
layout (location = 4) in float in_angle;      // instance: degrees (blast heading)

out vec2 v_uv;

uniform mat4 u_view_proj;
uniform sampler2DArray u_texture;
uniform float u_spriteSize;                   // 16 px cells
uniform float u_depth;
uniform float u_layer_spread;
uniform float u_texLayer;

void main() {
    vec2 texSize = textureSize(u_texture, 0).xy;
    vec2 uvStep = vec2(u_spriteSize / texSize.x, u_spriteSize / texSize.y);
    v_uv = in_frameUV + in_texCoord * uvStep;

    float c = cos(radians(in_angle));
    float s = sin(radians(in_angle));
    vec2 quad = vec2(in_pos.x * c - in_pos.y * s, in_pos.x * s + in_pos.y * c);

    vec2 world = quad * u_spriteSize + in_worldPos;
    gl_Position = u_view_proj * vec4(world.x, world.y, u_depth * u_layer_spread, 1.0);
}
