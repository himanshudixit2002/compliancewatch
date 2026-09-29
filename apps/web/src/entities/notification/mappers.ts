import type { Preference, PreferenceChange, PreferenceDto, PreferenceInDto } from "./types";

export function preferenceFromDto(dto: PreferenceDto): Preference {
  return {
    channel: dto.channel,
    recipient: dto.recipient,
    optedIn: dto.opted_in,
    source: dto.source,
    language: dto.language,
    quietHoursStart: dto.quiet_hours_start,
    quietHoursEnd: dto.quiet_hours_end,
    updatedAt: dto.updated_at,
  };
}

/** The PUT body; the language and the quiet hours travel only when set. */
export function preferenceChangeToDto(change: PreferenceChange): PreferenceInDto {
  const dto: PreferenceInDto = { opted_in: change.optedIn, source: change.source };
  if (change.language !== undefined) dto.language = change.language;
  if (change.quietHoursStart !== undefined) dto.quiet_hours_start = change.quietHoursStart;
  if (change.quietHoursEnd !== undefined) dto.quiet_hours_end = change.quietHoursEnd;
  return dto;
}
