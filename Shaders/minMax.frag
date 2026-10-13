#version 400 core

in vec2 TexCoords;
out vec4 FragColor;

uniform sampler2D inputTexture;
uniform bool firstPass;

void main()
{
    // Get input texture size
    ivec2 inputSize = textureSize(inputTexture, 0);

    // Calculate which 2x2 block this output pixel corresponds to
    // gl_FragCoord.xy gives us the output pixel position (0.5, 0.5) for first pixel
    ivec2 outputPixel = ivec2(gl_FragCoord.xy);
    ivec2 inputBase = outputPixel * 2;

    float minValue = 1.0e38;
    float maxValue = -1.0e38;
    float sum = 0.0;
    int count = 0;

    for (int i = 0; i <= 1; ++i)
    {
        for (int j = 0; j <= 1; ++j)
        {
            ivec2 inputPixel = inputBase + ivec2(i, j);

            // Skip out of bounds
            if (inputPixel.x >= inputSize.x || inputPixel.y >= inputSize.y)
                continue;

            vec4 color = texelFetch(inputTexture, inputPixel, 0);

            if (firstPass)
            {
                float raw = color.r;
                if (isnan(raw))
                    continue;

                float value = abs(raw);
                if (value <= 0.0)
                    continue;

                minValue = min(minValue, value);
                maxValue = max(maxValue, value);
                count += 1;
                sum += value;
            }
            else
            {
                float v1 = color.r; // MIN
                float v2 = color.g; // MAX

                // Check for valid values (not sentinel 1.0e38 or -1.0e38)
                if (v1 < 1.0e37)
                {
                    minValue = min(minValue, v1);
                }
                if (v2 > -1.0e37)
                {
                    maxValue = max(maxValue, v2);
                }

                count += int(color.b);
                sum += color.a;
            }
        }
    }

    FragColor = vec4(minValue, maxValue, float(count), sum);
}
