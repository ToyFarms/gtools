#version 450 core

out vec4 out_fragColor;
in vec2 texCoord;
flat in float layer;
uniform sampler2DArray texArray;
uniform float u_pixelScale;
uniform vec3 u_tint;

void main() {
    vec2 texSize = textureSize(texArray, 0).xy;

    vec2 pixelatedUV = ceil(texCoord * texSize / u_pixelScale) * u_pixelScale / texSize;

    vec2 halfTexel = vec2(0.5) / texSize;
    pixelatedUV = clamp(pixelatedUV, halfTexel, 1.0 - halfTexel);

    out_fragColor = texture(texArray, vec3(pixelatedUV, layer));
    if (out_fragColor.a < 0.001) discard;
    out_fragColor.rgb *= out_fragColor.a * u_tint;
}
