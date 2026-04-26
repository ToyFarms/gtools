#version 450 core

out vec4 out_fragColor;
in vec4 tint;
in vec2 texCoord;
flat in float layer;
uniform sampler2DArray texArray;
uniform float u_pixelScale;

void main() {
    vec2 texSize = textureSize(texArray, 0).xy;

    vec2 pixelatedUV = (floor(texCoord * texSize / u_pixelScale) + 0.5) * u_pixelScale / texSize;

    vec2 halfTexel = vec2(0.5) / texSize;
    pixelatedUV = clamp(pixelatedUV, halfTexel, 1.0 - halfTexel);

    out_fragColor = texture(texArray, vec3(pixelatedUV, layer));
    out_fragColor.a *= tint.a;
    if (out_fragColor.a < 0.001) discard;
    out_fragColor.rgb *= out_fragColor.a * tint.rgb;
}
