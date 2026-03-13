#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;

layout (location = 2) in vec3 in_tilePos;
layout (location = 3) in vec3 in_baseColor;
layout (location = 4) in vec3 in_overlayColor;
layout (location = 5) in float in_baseUV;
layout (location = 6) in float in_overlayUV;
layout (location = 7) in float in_layer;

out vec2 baseTexCoord;
out vec2 overlayTexCoord;
out vec3 baseTint;
out vec3 overlayTint;
flat out float layer;

uniform mat4 u_view_proj;
uniform sampler2DArray u_texture;
uniform float u_layer_spread;

void main() {
    vec2 texSize = textureSize(u_texture, 0).xy;
    float uStep     = 16.0 / texSize.x;
    float rowHeight = 16.0 / texSize.y;

    baseTexCoord    = vec2(in_baseUV    + in_texCoord.x * uStep, in_texCoord.y * rowHeight);
    overlayTexCoord = vec2(in_overlayUV + in_texCoord.x * uStep, rowHeight + in_texCoord.y * rowHeight);

    baseTint    = in_baseColor;
    overlayTint = in_overlayColor;

    vec2 worldPos = in_pos * 16.0 * 1.34 + in_tilePos.xy;
    float z = in_tilePos.z * u_layer_spread;
    gl_Position = u_view_proj * vec4(worldPos.x, worldPos.y, z, 1.0);
    layer = in_layer;
}
