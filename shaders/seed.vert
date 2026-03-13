#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;

layout (location = 2) in vec3 in_tilePos;
layout (location = 3) in vec3 in_baseColor; // TODO: color can be encoded as uint32, but it would require some changes to the Mesh class
layout (location = 4) in vec3 in_overlayColor;
layout (location = 5) in float in_baseUV;
layout (location = 6) in float in_overlayUV;
layout (location = 7) in float in_layer;

out vec2 baseTexCoord;
out vec2 overlayTexCoord;
out vec3 baseTint;
out vec3 overlayTint;
flat out float layer;
uniform mat4 u_mvp;
uniform sampler2DArray u_texture;

void main() {
    vec2 texSize = textureSize(u_texture, 0).xy;
    float uStep = 16.0 / texSize.x;
    float rowHeight = 16.0 / texSize.y;

    baseTexCoord = vec2(in_baseUV + in_texCoord.x * uStep, in_texCoord.y * rowHeight);
    overlayTexCoord = vec2(in_overlayUV + in_texCoord.x * uStep, rowHeight + in_texCoord.y * rowHeight);

    baseTint = in_baseColor;
    overlayTint = in_overlayColor;

    vec2 worldPos = in_pos * 16.0 + in_tilePos.xy;
    gl_Position = u_mvp * vec4(worldPos, in_tilePos.z, 1.0);
    layer = in_layer;
}
