/**
 * conversion between how a cook states a step's durations and how a step stores them (REQ-008)
 *
 * the model keeps `time` as the step's *total elapsed* minutes - which is what the step timer counts
 * down and what REQ-004's bake schedule chains over - and `working_time` as the attended portion
 * carved out of it. the waiting portion is the remainder and is never stored.
 *
 * an author, though, knows the two durations directly: "knead for 10 minutes, then let it ferment for
 * an hour". this module is the only place that translates between the two, so no component holds the
 * arithmetic and the whole conversion is gradable by vitest.
 */

/**
 * the two durations a cook states, in minutes
 *
 * by convention the work comes first and the wait follows it, which is how recipes are written and
 * what lets a schedule chain the pair as one stretch of elapsed time
 */
export interface StepDurations {
    working: number
    waiting: number
}

/**
 * the pair as a step stores it, in minutes
 */
export interface StoredStepTime {
    time: number
    workingTime: number
}

/**
 * reduces a stored or entered duration to a number that can be used in arithmetic
 *
 * anything that is not a finite positive number - zero, null, undefined, NaN, a negative - counts as
 * no time at all, so a missing value can never produce a negative waiting portion
 *
 * @param minutes duration as entered or as stored on a step
 * @returns minutes, never negative
 */
function normalize(minutes: number | null | undefined): number {
    if (minutes === null || minutes === undefined || !Number.isFinite(minutes) || minutes <= 0) {
        return 0
    }
    return minutes
}

/**
 * converts the durations a cook states into the pair a step stores
 *
 * @param working attended minutes
 * @param waiting unattended minutes that follow them
 * @returns the stored pair, where time is the total the timer runs for
 */
export function toStoredStepTime(working: number | null | undefined, waiting: number | null | undefined): StoredStepTime {
    const attended = normalize(working)
    const unattended = normalize(waiting)

    return {time: attended + unattended, workingTime: attended}
}

/**
 * converts the pair a step stores back into the durations a cook states
 *
 * `workingTime` is clamped into `[0, time]` rather than trusted. the model rejects a step whose working
 * time exceeds its total, but a row that predates that rule - or one written by something that bypassed
 * validation - must still display as something rather than as a negative wait
 *
 * @param time total elapsed minutes as stored
 * @param workingTime attended minutes as stored
 * @returns the two durations, neither ever negative
 */
export function fromStoredStepTime(time: number | null | undefined, workingTime: number | null | undefined): StepDurations {
    const total = normalize(time)
    const attended = Math.min(normalize(workingTime), total)

    return {working: attended, waiting: total - attended}
}
