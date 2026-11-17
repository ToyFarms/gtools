#version 450 core

// The one sprite pipeline for the world scene: every RenderCommand (tiles,
// object icons, overlays, drop shadows) becomes an instance of this quad.
// Instances are positioned in GUI world space (tiles centred at x * 32) by
// gtools.gui.lib.sprite_batch.command_instances.

layout (location = 0) in vec2 in_pos;        // quad corner, -0.5..0.5
layout (location = 1) in vec2 in_texCoord;   // 0..1

layout (location = 2) in vec2 in_spritePos;  // centre, world px
layout (location = 3) in vec2 in_spriteSize; // px
layout (location = 4) in vec4 in_texCoords;  // u0 v0 u1 v1
layout (location = 5) in float in_texLayer;
layout (location = 6) in float in_depth;
layout (location = 7) in float in_paintIndex;
layout (location = 8) in uint in_tint;
layout (location = 9) in float in_opacity;

out vec2 texCoord;
flat out float texLayer;
flat out float paintIndex;
flat out uint tint;
flat out float opacity;

uniform mat4 u_mvp;

void main() {
    vec2 worldPos = in_spritePos + in_pos * in_spriteSize;
    gl_Position = u_mvp * vec4(worldPos, in_depth, 1.0);

    texCoord = vec2(
        mix(in_texCoords.x, in_texCoords.z, in_texCoord.x),
        mix(in_texCoords.y, in_texCoords.w, in_texCoord.y)
    );
    texLayer = in_texLayer;
    paintIndex = in_paintIndex;
    tint = in_tint;
    opacity = in_opacity;
}
