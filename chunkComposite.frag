#version 400 core

in vec2 TexCoord;
out float FragColor;

uniform sampler2D chunkTexture;

// How many chunk texels map to one composite pixel
// Values > 1 mean we're zoomed out and need to max-sample multiple texels
uniform vec2 texelsPerPixel;

// Chunk texture size (typically 128x128)
uniform vec2 chunkSize;

void main()
{
    // If texelsPerPixel <= 1, just sample normally (zoomed in or 1:1)
    if (texelsPerPixel.x <= 1.0 && texelsPerPixel.y <= 1.0)
    {
        FragColor = texture(chunkTexture, TexCoord).r;
        return;
    }

    // Calculate how many texels we need to sample in each direction
    // Round up to ensure we cover all contributing texels
    int samplesX = max(1, int(ceil(texelsPerPixel.x)));
    int samplesY = max(1, int(ceil(texelsPerPixel.y)));

    // Limit max samples for performance (16x16 = 256 samples max)
    samplesX = min(samplesX, 16);
    samplesY = min(samplesY, 16);

    // Size of one texel in UV space
    vec2 texelSize = 1.0 / chunkSize;

    // Calculate the UV range that maps to this pixel
    // Center the sampling region around TexCoord
    vec2 halfRange = texelSize * texelsPerPixel * 0.5;
    vec2 startUV = TexCoord - halfRange;
    vec2 stepUV = texelSize * texelsPerPixel / vec2(samplesX, samplesY);

    // Sample all texels and take maximum absolute value
    // For split mode: positive = bid, negative = ask
    // We want max(abs()) but preserve sign of the maximum
    float maxAbsValue = 0.0;
    float resultValue = 0.0;

    for (int y = 0; y < samplesY; y++)
    {
        for (int x = 0; x < samplesX; x++)
        {
            vec2 sampleUV = startUV + stepUV * (vec2(x, y) + 0.5);

            // Clamp to valid UV range
            sampleUV = clamp(sampleUV, vec2(0.0), vec2(1.0));

            float value = texture(chunkTexture, sampleUV).r;
            float absValue = abs(value);

            if (absValue > maxAbsValue)
            {
                maxAbsValue = absValue;
                resultValue = value;
            }
        }
    }

    FragColor = resultValue;
}
