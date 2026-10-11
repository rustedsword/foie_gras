# Project artwork

[`goose.jpg`](goose.jpg) is an optimized copy of the supplied "Code-Fed Goose
Feast.png" illustration, used in the project README. It preserves the full scene
at 960 × 800 pixels and displays at 480 × 400 pixels.

[`social-preview.png`](social-preview.png) is a 1280 × 640 image ready for GitHub.
Upload it under [repository Settings](https://github.com/rustedsword/foie_gras/settings)
→ **Social preview** → **Edit** → **Upload an image**. Committing the image does
not set the repository's social preview automatically. See the
[GitHub guide](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview).

To rebuild the PNG after changing the artwork or `social-preview.svg`, install `rsvg-convert` and the
Liberation fonts, then run from the repository root:

```sh
rsvg-convert --output assets/social-preview.png assets/social-preview.svg
```
