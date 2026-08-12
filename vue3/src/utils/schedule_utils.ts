import {DateTime, WeekdayNumbers} from 'luxon'

/**
 * labels used when rendering a start time
 * passed in by the caller so that no display string is ever inlined in the scheduling logic
 */
export interface ScheduleLabels {
    today: string
    tomorrow: string
}

/**
 * English fallbacks, used when a caller has no i18n context (tests, plain scripts)
 */
export const DEFAULT_SCHEDULE_LABELS: ScheduleLabels = {today: 'Today', tomorrow: 'Tomorrow'}

/**
 * the parts of a step the scheduler cares about, a structural subset of the generated Step model
 */
export interface ScheduleStep {
    name?: string | null
    time?: number | null
    stepRecipe?: number | null
}

/**
 * a step whose duration cannot describe the work it stands for, because it delegates to a sub recipe
 * the scheduler does not look into
 */
export interface UnschedulableStep {
    index: number
    name: string
}

/**
 * the back chained schedule of a recipe
 */
export interface RecipeSchedule {
    /** when the first step has to start, equal to the finish time for an empty or all zero step list */
    overallStart: DateTime
    /** when each step has to start, positionally aligned with the durations it was built from */
    stepStarts: DateTime[]
}

/**
 * number of days a start lies away from the reference beyond which a bare weekday is ambiguous
 */
const BARE_WEEKDAY_REACH = 6

/**
 * reduces a stored duration to the minutes the scheduler may subtract
 *
 * anything that is not a finite positive number - zero, null, undefined, NaN, a negative - counts as no
 * time at all, which is what makes a zero duration step start exactly when the step after it starts
 *
 * @param minutes duration as stored on a step
 * @returns minutes to subtract, never negative
 */
function schedulableMinutes(minutes: number | null | undefined): number {
    if (minutes === null || minutes === undefined || !Number.isFinite(minutes) || minutes <= 0) {
        return 0
    }
    return minutes
}

/**
 * back chains the start times of a recipe from the time it has to be finished
 *
 * the last step ends at the finish time, every earlier step ends when the step after it starts. durations
 * are subtracted as absolute time, so a chain crossing a daylight saving boundary keeps the elapsed time
 * a ferment actually takes and shifts the wall clock instead
 *
 * @param finish when the recipe has to be done
 * @param durations step durations in minutes, in step order
 * @returns the start of every step plus the overall start
 */
export function backChainSchedule(finish: DateTime, durations: (number | null | undefined)[]): RecipeSchedule {
    const stepStarts: DateTime[] = new Array(durations.length)

    let start = finish
    for (let index = durations.length - 1; index >= 0; index--) {
        start = start.minus({minutes: schedulableMinutes(durations[index])})
        stepStarts[index] = start
    }

    return {overallStart: start, stepStarts: stepStarts}
}

/**
 * renders a start time relative to a reference moment, as a weekday and a time of day
 *
 * the day distance is counted in calendar days rather than elapsed hours, so a start that is only a few
 * hours away but on the other side of midnight reads as tomorrow. Beyond a week in either direction the
 * weekday alone no longer identifies a day, so an explicit signed day offset is appended. A calendar date
 * is never emitted
 *
 * @param start when the step has to start
 * @param reference the moment the start is described relative to, normally now
 * @param labels translated labels for the two nearest days
 * @returns the formatted start time
 */
export function formatStartTime(start: DateTime, reference: DateTime, labels: ScheduleLabels = DEFAULT_SCHEDULE_LABELS): string {
    const timeOfDay = start.toFormat('HH:mm')
    const dayOffset = Math.round(start.startOf('day').diff(reference.startOf('day'), 'days').days)

    if (dayOffset === 0) {
        return `${labels.today} ${timeOfDay}`
    }
    if (dayOffset === 1) {
        return `${labels.tomorrow} ${timeOfDay}`
    }

    const weekday = `${start.toLocaleString({weekday: 'short'})} ${timeOfDay}`
    if (Math.abs(dayOffset) <= BARE_WEEKDAY_REACH) {
        return weekday
    }
    return `${weekday} (${dayOffset > 0 ? '+' : '-'}${Math.abs(dayOffset)} d)`
}

/**
 * resolves a weekday and a time of day to the next upcoming occurrence of that weekday
 *
 * a weekday that is today counts only while its time is still ahead, picking the same day next week once
 * the time has passed. Whole weeks are added calendar wise, so the chosen wall clock time survives a
 * daylight saving boundary
 *
 * @param weekday ISO weekday, 1 is Monday through 7 is Sunday
 * @param hour hour of day, 0 through 23
 * @param minute minute of hour, 0 through 59
 * @param reference the moment the occurrence has to be after, normally now
 * @returns the next occurrence, always strictly after the reference
 */
export function nextOccurrence(weekday: WeekdayNumbers, hour: number, minute: number, reference: DateTime): DateTime {
    let occurrence = reference.set({weekday: weekday, hour: hour, minute: minute, second: 0, millisecond: 0})

    while (occurrence <= reference) {
        occurrence = occurrence.plus({weeks: 1})
    }
    return occurrence
}

/**
 * serializes a finish time for the query parameter it lives in
 *
 * written in UTC so the value carries no literal plus sign, the one character a query string reads back as
 * a space whenever anything along the way mishandles the encoding
 *
 * @param finish the finish time to write to the url
 * @returns the serialized instant
 */
export function serializeFinishTime(finish: DateTime): string {
    return finish.toUTC().toISO({suppressMilliseconds: true})!
}

/**
 * parses a finish time out of the query parameter it lives in
 *
 * @param value the raw query parameter, of whatever shape the url happened to carry
 * @param zone the zone the finish time should be read in, the system zone by default
 * @returns the finish time, or undefined for an absent or malformed value
 */
export function parseFinishTime(value: unknown, zone?: string): DateTime | undefined {
    if (typeof value !== 'string' || value === '') {
        return undefined
    }

    const finish = DateTime.fromISO(value, {zone: zone ?? 'system'})
    return finish.isValid ? finish : undefined
}

/**
 * finds the steps that make the schedule incomplete
 *
 * a step delegating to a sub recipe while carrying no duration of its own hides however long that sub
 * recipe takes, which would make every earlier start time silently late. The schedule is not wrong about
 * such a step, it is wrong about every step before it, so the case is reported rather than guessed at
 *
 * @param steps the steps of the recipe, in step order
 * @returns one entry per offending step, empty when the schedule is complete
 */
export function findUnschedulableSteps(steps: ScheduleStep[]): UnschedulableStep[] {
    const unschedulable: UnschedulableStep[] = []

    steps.forEach((step, index) => {
        const hasSubRecipe = step.stepRecipe !== null && step.stepRecipe !== undefined
        if (hasSubRecipe && schedulableMinutes(step.time) === 0) {
            unschedulable.push({index: index, name: step.name ?? ''})
        }
    })

    return unschedulable
}
