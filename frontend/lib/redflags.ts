// Client-side mirror of the deterministic safety net (backend/app/config/red_flags.yaml).
// It lets the emergency screen appear instantly even if the API is slow; the backend runs the
// authoritative check on every message and marks the case urgent for the clinic.

const norm = (s: string) =>
  s.toLowerCase().replace(/ł/g, "l").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim();

const PATTERNS: RegExp[] = [
  /chest (pain|pains|ache|hurts|tightness|pressure)|pain (in|across|around) (my |the )?chest|(tight|heavy|crushing) (feeling in (my |the )?)?chest|my chest (hurts|is tight|feels tight)/,
  /bol (w|na) klat|(ucisk|klucie|pieczenie|gniecenie) w klat|boli mnie (w )?klat/,
  /can'?t breathe|cannot breathe|(difficulty|trouble|struggling) (to )?breath|short of breath (at|while|when) rest|gasping for (air|breath)|choking/,
  /nie moge (zlapac )?(oddechu|oddychac)|dusze sie|brak(uje mi)? tchu|duszno mi/,
  /faint(ed|ing)|passed out|(lost|losing) consciousness|blacked out|zemdlal|stracil\w* przytomnosc/,
  /face (is )?(drooping|droops)|slurred speech|can'?t (move|feel) (my |one )?(arm|leg|side)|belkot/,
  /(lips|face) (are |is |turned |turning )?blue|sine (usta|wargi)/,
  /throat (is )?(closing|swelling|swollen)|puchnie mi (gardlo|jezyk)/,
  /worst headache|sudden (severe|very bad|explosive) headache|najgorszy bol glowy/,
  /kill myself|suicid|don'?t want to (live|be alive)|nie chce zyc|zabic sie|samoboj/,
];
const CONTEXTUAL = /(breath|tchu|oddech|duszn).*\|\|.*(even when resting|at rest|nawet w spoczynku|w spoczynku)/;

export function isRedFlag(text: string, question = ""): boolean {
  const n = norm(text);
  return PATTERNS.some((p) => p.test(n)) || CONTEXTUAL.test(`${norm(question)} || ${n}`);
}
