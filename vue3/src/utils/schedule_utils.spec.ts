import {describe, expect, it} from 'vitest'
import {DateTime, WeekdayNumbers} from 'luxon'
import {
    backChainSchedule,
    findUnschedulableSteps,
    formatStartTime,
    nextOccurrence,
    parseFinishTime,
    ScheduleStep,
    serializeFinishTime,
} from '@/utils/schedule_utils'

const ZONE = 'Europe/Berlin'
const LABELS = {today: 'Today', tomorrow: 'Tomorrow'}

/**
 * a fixed reference moment, Thursday 13 August 2026 at 09:00, so that every weekday assertion below is a
 * constant rather than a value derived from the code under test
 */
const REFERENCE = DateTime.fromISO('2026-08-13T09:00', {zone: ZONE}).setLocale('en')

function berlin(iso: string): DateTime {
    return DateTime.fromISO(iso, {zone: ZONE}).setLocale('en')
}

function wallClock(value: DateTime): string {
    return value.toFormat('ccc yyyy-MM-dd HH:mm ZZ')
}

function wallClocks(values: DateTime[]): string[] {
    return values.map(wallClock)
}

describe('backChainSchedule', () => {
    const finish = berlin('2026-08-23T12:00')

    /**
     * the chain the AC describes, spelled out as "this many minutes before the finish" per step, so that
     * the expectation is built by the rule rather than by the implementation
     */
    function minutesBeforeFinish(...offsets: number[]): string[] {
        return wallClocks(offsets.map((offset) => finish.minus({minutes: offset})))
    }

    it('starts the last step its own duration before the finish and each earlier step before the next', () => {
        const {stepStarts} = backChainSchedule(finish, [30, 60, 90])

        expect(wallClocks(stepStarts)).toEqual(minutesBeforeFinish(90 + 60 + 30, 90 + 60, 90))
    })

    it('returns one start per step', () => {
        expect(backChainSchedule(finish, [30, 60, 90]).stepStarts).toHaveLength(3)
        expect(backChainSchedule(finish, [15]).stepStarts).toHaveLength(1)
    })

    it('reports the first steps start as the overall start', () => {
        const {overallStart} = backChainSchedule(finish, [30, 60, 90])

        expect(wallClocks([overallStart])).toEqual(minutesBeforeFinish(180))
    })

    it.each([
        ['zero', 0],
        ['null', null],
        ['undefined', undefined],
    ])('starts a step of duration %s exactly when the following step starts', (_label, duration) => {
        const {stepStarts} = backChainSchedule(finish, [60, duration, 90])

        expect(wallClocks(stepStarts)).toEqual(minutesBeforeFinish(90 + 60, 90, 90))
    })

    it('yields an overall start equal to the finish for an empty step list', () => {
        const {overallStart, stepStarts} = backChainSchedule(finish, [])

        expect(wallClock(overallStart)).toBe(wallClock(finish))
        expect(stepStarts).toHaveLength(0)
    })

    it('yields an overall start equal to the finish and no offsets for an all zero step list', () => {
        const {overallStart, stepStarts} = backChainSchedule(finish, [0, 0, 0])

        expect(wallClock(overallStart)).toBe(wallClock(finish))
        expect(wallClocks(stepStarts)).toEqual(minutesBeforeFinish(0, 0, 0))
    })

    it('lands on the correct wall clock across two midnights and a spring forward boundary', () => {
        // Europe/Berlin moves 02:00 -> 03:00 on Sunday 29 March 2026, so the night before the finish only
        // has 23 wall clock hours. Three 24 hour steps therefore start an hour earlier by the clock than
        // the finish time, not at the same time of day
        const {overallStart, stepStarts} = backChainSchedule(berlin('2026-03-29T12:00'), [1440, 1440, 1440])

        expect(wallClocks(stepStarts)).toEqual([
            'Thu 2026-03-26 11:00 +01:00',
            'Fri 2026-03-27 11:00 +01:00',
            'Sat 2026-03-28 11:00 +01:00',
        ])
        expect(wallClock(overallStart)).toBe('Thu 2026-03-26 11:00 +01:00')
    })

    it('lands on the correct wall clock across a fall back boundary', () => {
        // the reverse case, the night gains an hour so the same 24 hour step starts an hour later by the clock
        const {stepStarts} = backChainSchedule(berlin('2026-10-25T12:00'), [1440, 1440])

        expect(wallClocks(stepStarts)).toEqual(['Fri 2026-10-23 13:00 +02:00', 'Sat 2026-10-24 13:00 +02:00'])
    })

    it('does not run backwards on a negative or non finite duration', () => {
        const {stepStarts} = backChainSchedule(finish, [NaN, -120, 60])

        expect(wallClocks(stepStarts)).toEqual(minutesBeforeFinish(60, 60, 60))
    })
})

describe('formatStartTime', () => {
    it('renders a start on the reference day as the today form', () => {
        expect(formatStartTime(berlin('2026-08-13T18:30'), REFERENCE, LABELS)).toBe('Today 18:30')
    })

    it('renders a start on the reference day that has already passed as the today form', () => {
        expect(formatStartTime(berlin('2026-08-13T06:00'), REFERENCE, LABELS)).toBe('Today 06:00')
    })

    it('renders a start on the next day as the tomorrow form', () => {
        expect(formatStartTime(berlin('2026-08-14T06:00'), REFERENCE, LABELS)).toBe('Tomorrow 06:00')
    })

    it('counts calendar days rather than elapsed hours', () => {
        // four hours later, but on the other side of midnight
        expect(formatStartTime(berlin('2026-08-14T01:00'), berlin('2026-08-13T21:00'), LABELS)).toBe('Tomorrow 01:00')
    })

    it.each([
        ['2026-08-15T18:30', 'Sat 18:30'],
        ['2026-08-19T06:00', 'Wed 06:00'],
        ['2026-08-11T07:15', 'Tue 07:15'],
        ['2026-08-08T22:00', 'Sat 22:00'],
        ['2026-08-12T18:30', 'Wed 18:30'],
    ])('renders a start within six days either way (%s) as a bare weekday: %s', (start, expected) => {
        expect(formatStartTime(berlin(start), REFERENCE, LABELS)).toBe(expected)
    })

    it.each([
        ['2026-08-20T06:00', 'Thu 06:00 (+7 d)'],
        ['2026-08-22T18:30', 'Sat 18:30 (+9 d)'],
        ['2026-08-04T18:30', 'Tue 18:30 (-9 d)'],
        ['2026-08-06T09:30', 'Thu 09:30 (-7 d)'],
    ])('appends a signed day offset beyond six days (%s): %s', (start, expected) => {
        expect(formatStartTime(berlin(start), REFERENCE, LABELS)).toBe(expected)
    })

    it('never emits a calendar date', () => {
        const starts = ['2026-08-13T18:30', '2026-08-14T06:00', '2026-08-15T18:30', '2026-08-22T18:30', '2026-08-04T18:30']

        starts.forEach((start) => {
            const rendered = formatStartTime(berlin(start), REFERENCE, LABELS)
            expect(rendered).not.toMatch(/\d{4}/)
            expect(rendered).not.toMatch(/\d+[./-]\d+/)
        })
    })

    it('takes the weekday name from the locale of the start rather than an inlined table', () => {
        const start = berlin('2026-08-15T18:30').setLocale('de')

        expect(formatStartTime(start, REFERENCE, LABELS)).toBe('Sa 18:30')
    })

    it('uses the labels it is given rather than inlined words', () => {
        expect(formatStartTime(berlin('2026-08-13T18:30'), REFERENCE, {today: 'Heute', tomorrow: 'Morgen'})).toBe('Heute 18:30')
        expect(formatStartTime(berlin('2026-08-14T06:00'), REFERENCE, {today: 'Heute', tomorrow: 'Morgen'})).toBe('Morgen 06:00')
    })

    it('defaults to english labels', () => {
        expect(formatStartTime(berlin('2026-08-13T18:30'), REFERENCE)).toBe('Today 18:30')
    })
})

describe('nextOccurrence', () => {
    it('resolves a weekday later in the week to that day of this week', () => {
        // the reference is a Thursday, Saturday is still ahead of it
        expect(wallClock(nextOccurrence(6, 18, 30, REFERENCE))).toBe('Sat 2026-08-15 18:30 +02:00')
    })

    it('resolves a weekday earlier in the week to that day of next week', () => {
        expect(wallClock(nextOccurrence(2, 7, 0, REFERENCE))).toBe('Tue 2026-08-18 07:00 +02:00')
    })

    it('resolves a monday chosen on a sunday to tomorrow rather than six days ago', () => {
        // the ISO week runs Monday to Sunday, so the naive same week answer would be in the past
        expect(wallClock(nextOccurrence(1, 7, 0, berlin('2026-08-16T09:00')))).toBe('Mon 2026-08-17 07:00 +02:00')
    })

    it('keeps a time later today on today', () => {
        expect(wallClock(nextOccurrence(4, 18, 30, REFERENCE))).toBe('Thu 2026-08-13 18:30 +02:00')
    })

    it('rolls a week when the weekday is today but the time has already passed', () => {
        expect(wallClock(nextOccurrence(4, 6, 0, REFERENCE))).toBe('Thu 2026-08-20 06:00 +02:00')
    })

    it('rolls a week when the weekday is today at exactly the reference time', () => {
        expect(wallClock(nextOccurrence(4, 9, 0, REFERENCE))).toBe('Thu 2026-08-20 09:00 +02:00')
    })

    it.each<WeekdayNumbers>([1, 2, 3, 4, 5, 6, 7])('is strictly after the reference for weekday %i', (weekday) => {
        expect(nextOccurrence(weekday, 9, 0, REFERENCE) > REFERENCE).toBe(true)
    })

    it('keeps the chosen wall clock time across a daylight saving boundary', () => {
        // Sunday 22 March at 09:00 is CET, the next Sunday is CEST, and 06:00 still means 06:00
        expect(wallClock(nextOccurrence(7, 6, 0, berlin('2026-03-22T09:00')))).toBe('Sun 2026-03-29 06:00 +02:00')
    })

    it('zeroes the seconds of the reference', () => {
        const occurrence = nextOccurrence(6, 18, 30, berlin('2026-08-13T09:00:37.123'))

        expect(occurrence.second).toBe(0)
        expect(occurrence.millisecond).toBe(0)
    })
})

describe('serializeFinishTime and parseFinishTime', () => {
    it('round trips a finish time to the same instant', () => {
        const finish = berlin('2026-08-23T12:00')

        const parsed = parseFinishTime(serializeFinishTime(finish), ZONE)

        expect(parsed).toBeDefined()
        expect(parsed!.toMillis()).toBe(finish.toMillis())
    })

    it('round trips the wall clock of the zone it is read in', () => {
        const parsed = parseFinishTime(serializeFinishTime(berlin('2026-08-23T12:00')), ZONE)

        expect(wallClock(parsed!)).toBe('Sun 2026-08-23 12:00 +02:00')
    })

    it('round trips across a daylight saving boundary', () => {
        const finish = berlin('2026-03-29T12:00')

        expect(wallClock(parseFinishTime(serializeFinishTime(finish), ZONE)!)).toBe('Sun 2026-03-29 12:00 +02:00')
    })

    it('serializes without a literal plus sign, which a query string would read back as a space', () => {
        expect(serializeFinishTime(berlin('2026-08-23T12:00'))).toBe('2026-08-23T10:00:00Z')
    })

    it.each([
        ['an absent param', undefined],
        ['a null param', null],
        ['an empty param', ''],
    ])('yields no finish time for %s', (_label, value) => {
        expect(parseFinishTime(value, ZONE)).toBeUndefined()
    })

    it.each([
        ['plain nonsense', 'banana'],
        ['an impossible date', '2026-13-45T99:99:99Z'],
        ['a half written date', '2026-08-'],
        ['a number', 1755943200000],
        ['a repeated param read as an array', ['2026-08-23T10:00:00Z', '2026-08-24T10:00:00Z']],
    ])('yields no finish time rather than throwing for %s', (_label, value) => {
        expect(() => parseFinishTime(value, ZONE)).not.toThrow()
        expect(parseFinishTime(value, ZONE)).toBeUndefined()
    })
})

describe('findUnschedulableSteps', () => {
    function step(overrides: Partial<ScheduleStep>): ScheduleStep {
        return {name: '', time: 60, stepRecipe: null, ...overrides}
    }

    it.each([
        ['zero', 0],
        ['null', null],
        ['undefined', undefined],
    ])('reports a sub recipe step carrying a duration of %s', (_label, time) => {
        const unschedulable = findUnschedulableSteps([step({}), step({name: 'Levain', time: time, stepRecipe: 7})])

        expect(unschedulable).toEqual([{index: 1, name: 'Levain'}])
    })

    it('reports the step by position when it has no name', () => {
        const unschedulable = findUnschedulableSteps([step({time: 0, stepRecipe: 7})])

        expect(unschedulable).toEqual([{index: 0, name: ''}])
    })

    it('reports every offending step in step order', () => {
        const unschedulable = findUnschedulableSteps([
            step({name: 'Levain', time: 0, stepRecipe: 7}),
            step({name: 'Mix'}),
            step({name: 'Soaker', time: 0, stepRecipe: 9}),
        ])

        expect(unschedulable).toEqual([{index: 0, name: 'Levain'}, {index: 2, name: 'Soaker'}])
    })

    it('reports complete when a sub recipe step carries a duration of its own', () => {
        expect(findUnschedulableSteps([step({}), step({name: 'Levain', time: 720, stepRecipe: 7})])).toEqual([])
    })

    it('reports complete when no step carries a sub recipe reference', () => {
        expect(findUnschedulableSteps([step({}), step({time: 0}), step({time: null})])).toEqual([])
    })

    it('reports complete for an empty step list', () => {
        expect(findUnschedulableSteps([])).toEqual([])
    })
})
