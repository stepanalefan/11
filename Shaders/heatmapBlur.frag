#version 330 core

uniform sampler2D u_texture;
uniform float u_blurRadius;
uniform float u_textureHeight;

in vec2 TexCoord;
out vec4 FragColor;

void main() {
    
    int radius = int(ceil(u_blurRadius));
    float fraction = u_blurRadius - floor(u_blurRadius);
    
    float result = texture(u_texture, TexCoord).r;
    if (isnan(result))
    {
        FragColor = vec4(result, 0.0, 0.0, 1.0);
        return;
    }

    for (int i = -radius; i <= radius; i++) {
        if (i == 0) {
            continue;
        }

        float distNorm = abs(float(i) / float(u_blurRadius + 1.0));
        float brightness = (1.0 - distNorm * distNorm);

        float brightnessNorm = clamp(brightness, 0.0, 1.0);

        float volume = texture(u_texture, TexCoord + vec2(0.0, float(i) / u_textureHeight)).r;
        if (isnan(volume))
            continue;

        if (result != 0.0 && sign(result) != sign(volume))
            continue;

        if (abs(volume * brightnessNorm) > abs(result)) {
            result = volume * brightnessNorm;
        }
    }

    FragColor = vec4(result, 0.0, 0.0, 1.0);
}
