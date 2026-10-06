"""
Agents Routes - Lista as skills disponíveis a partir dos arquivos .Agent/Skill*.md
"""

import re
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from App.Core.Logs import info, error

# ── Router ────────────────────────────────────────────────────────────────────

agents_router = APIRouter(tags=["Agents"], prefix="/api/agents")

# ── Paths ─────────────────────────────────────────────────────────────────────

AGENT_DIR = (
    Path(__file__).parent.parent.parent.parent.parent
    / "App"
    / "Features"
    / "Agents"
    / "Agents"
    / ".Agent"
)

SKILL_GLOB = "Skill*.md"

# ── Skills excluídas temporariamente do catálogo ──────────────────────────────
# Remover entrada para reexibir a skill no frontend.

SKILLS_EXCLUDED: set[str] = {
    "SkillUserBrowsing.md",
    "SkillSocialMedia.md",
    "SkillCompetitorAnalysis.md",
    "SkillBusinessCanvas.md",
    "SkillBrandIdentity.md",
    "SkillCatalog.md",
    "SkillCopywriting.md",
    "SkillFunnelAnalyst.md",
    "SkillPaidCampaignReport.md",
}

# ── Regex de parse ────────────────────────────────────────────────────────────

_RE_HEADING_PREFIX = re.compile(r"^#+\s*")
_RE_SKILL_WORD = re.compile(r"\bSkill\b:?\s*", re.IGNORECASE)
_RE_EMOJI = re.compile(r"[\U0001F000-\U0001FFFF☀-➿]\s*")
_RE_OBJETIVO = re.compile(r"\*\*Objetivo:\*\*\s*(.+)")
_RE_BLOCKQUOTE = re.compile(r"^>\s*")
_RE_SKILL_PREFIX = re.compile(r"^Skill", re.IGNORECASE)
_RE_CAMEL_TO_KEBAB = re.compile(r"([A-Z])")

# ── Lookup prefix template ────────────────────────────────────────────────────

LOOKUP_PREFIX_TEMPLATE = 'Use a skill "{filename}" para: '

# ── Log tags ──────────────────────────────────────────────────────────────────

_TAG = "[AgentsRoutes]"

# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_skill_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # name: first # heading, stripped of emoji / "Skill:" prefix
    name = path.stem
    for line in lines:
        if line.startswith("#"):
            name = _RE_HEADING_PREFIX.sub("", line).strip()
            name = _RE_SKILL_WORD.sub("", name).strip()
            name = _RE_EMOJI.sub("", name).strip()
            break

    # description: first **Objetivo:** value OR first > blockquote
    description = ""
    for line in lines:
        m = _RE_OBJETIVO.match(line)
        if m:
            description = m.group(1).strip()
            break
        if line.startswith(">") and not description:
            candidate = _RE_BLOCKQUOTE.sub("", line).strip()
            if candidate:
                description = candidate

    # id: SkillCopywriting → copywriting
    skill_id = _RE_SKILL_PREFIX.sub("", path.stem)
    skill_id = _RE_CAMEL_TO_KEBAB.sub(
        lambda m: "-" + m.group(1).lower(), skill_id
    ).lstrip("-")

    lookup_prefix = LOOKUP_PREFIX_TEMPLATE.format(filename=path.name)

    return {
        "id": skill_id,
        "name": name,
        "description": description,
        "filename": path.name,
        "lookup_prefix": lookup_prefix,
    }


# ── Routes ────────────────────────────────────────────────────────────────────


@agents_router.get("/skills")
async def list_skills():
    try:
        if not AGENT_DIR.exists():
            error(f"{_TAG} .Agent dir not found: {AGENT_DIR}")
            return JSONResponse({"skills": []})

        skills = []
        for f in sorted(AGENT_DIR.glob(SKILL_GLOB)):
            if f.name in SKILLS_EXCLUDED:
                continue
            try:
                skills.append(_parse_skill_file(f))
            except Exception as e:
                error(f"{_TAG} Failed to parse {f.name}: {e}")

        info(f"{_TAG} Returning {len(skills)} skills")
        return JSONResponse({"skills": skills})
    except Exception as e:
        error(f"{_TAG} Error listing skills: {e}")
        return JSONResponse({"skills": []})
