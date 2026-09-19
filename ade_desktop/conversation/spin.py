"""The avatar's spinner words (adeos/avatar/chat.js SPIN_WORDS), verbatim:
while Ade works, a line in the chat itself says what it is "doing" --
Pondering, Noodling, Percolating -- a new word every 90 seconds, as the
avatar did. Ray, 2026-09-18: "return the spinners to chat area"."""

from __future__ import annotations

ROTATE_S = 90           # the avatar's interval between words

WORDS = (
    'Accomplishing', 'Actioning', 'Actualizing', 'Architecting', 'Baking', 'Beaming',
    "Beboppin'", 'Befuddling', 'Billowing', 'Blanching', 'Bloviating', 'Boogieing',
    'Boondoggling', 'Booping', 'Bootstrapping', 'Brewing', 'Bunning', 'Burrowing',
    'Calculating', 'Canoodling', 'Caramelizing', 'Cascading', 'Catapulting', 'Cerebrating',
    'Channeling', 'Channelling', 'Choreographing', 'Churning', 'Clauding', 'Coalescing',
    'Cogitating', 'Combobulating', 'Composing', 'Computing', 'Concocting', 'Considering',
    'Contemplating', 'Cooking', 'Crafting', 'Creating', 'Crunching', 'Crystallizing',
    'Cultivating', 'Deciphering', 'Deliberating', 'Determining', 'Dilly-dallying',
    'Discombobulating', 'Doing', 'Doodling', 'Drizzling', 'Ebbing', 'Effecting', 'Elucidating',
    'Embellishing', 'Enchanting', 'Envisioning', 'Fermenting', 'Fiddle-faddling', 'Finagling',
    'Flambéing', 'Flibbertigibbeting', 'Flowing', 'Flummoxing', 'Fluttering', 'Forging',
    'Forming', 'Frolicking', 'Frosting', 'Gallivanting', 'Galloping', 'Garnishing',
    'Generating', 'Gesticulating', 'Germinating', 'Gitifying', 'Grooving', 'Gusting',
    'Harmonizing', 'Hashing', 'Hatching', 'Herding', 'Honking', 'Hullaballooing',
    'Hyperspacing', 'Ideating', 'Imagining', 'Improvising', 'Incubating', 'Inferring',
    'Infusing', 'Ionizing', 'Jitterbugging', 'Julienning', 'Kneading', 'Leavening',
    'Levitating', 'Lollygagging', 'Manifesting', 'Marinating', 'Meandering', 'Metamorphosing',
    'Misting', 'Moonwalking', 'Moseying', 'Mulling', 'Mustering', 'Musing', 'Nebulizing',
    'Nesting', 'Newspapering', 'Noodling', 'Nucleating', 'Orbiting', 'Orchestrating',
    'Osmosing', 'Perambulating', 'Percolating', 'Perusing', 'Philosophising',
    'Photosynthesizing', 'Pollinating', 'Pondering', 'Pontificating', 'Pouncing',
    'Precipitating', 'Prestidigitating', 'Processing', 'Proofing', 'Propagating', 'Puttering',
    'Puzzling', 'Quantumizing', 'Razzle-dazzling', 'Razzmatazzing', 'Recombobulating',
    'Reticulating', 'Roosting', 'Ruminating', 'Sautéing', 'Scampering', 'Schlepping',
    'Scurrying', 'Seasoning', 'Shenaniganing', 'Shimmying', 'Simmering', 'Skedaddling',
    'Sketching', 'Slithering', 'Smooshing', 'Sock-hopping', 'Spelunking', 'Spinning',
    'Sprouting', 'Stewing', 'Sublimating', 'Swirling', 'Swooping', 'Symbioting',
    'Synthesizing', 'Tempering', 'Thinking', 'Thundering', 'Tinkering', 'Tomfoolering',
    'Topsy-turvying', 'Transfiguring', 'Transmuting', 'Twisting', 'Undulating', 'Unfurling',
    'Unravelling', 'Vibing', 'Waddling', 'Wandering', 'Warping', 'Whatchamacalliting',
    'Whirlpooling', 'Whirring', 'Whisking', 'Wibbling', 'Working', 'Wrangling', 'Zesting',
    'Zigzagging',
)
