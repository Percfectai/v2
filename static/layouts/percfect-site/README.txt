Percfect site pages (design handoff)
------------------------------------
home/    -> "Your Percfect World" homepage (neon hub: Create/Build/Play/Post/Re-up + Jukebox)
build/   -> Build page (Build Your Character / Comic Book / Hero Card)
create/  -> Create page (Perfect Pictures / Productions / Videos)

Each folder is a self-contained page: open index.html; images sit beside it (relative paths).

For the deployer:
- Nav links: the logo dropdown items and the neon buttons are <a href="#"> — set real hrefs.
- Wallet chips (credits/tickets) are sample numbers -> wire to live wallet.
- Jukebox (home): fill the PLAYLIST array in the inline script with title + src for each song.
- Library popup (spinning-P, bottom-right): fill with real library data.
- Fonts load from Google Fonts; everything else is inline or local.
