import {describe, expect, it} from 'vitest'
import {fromStoredStepTime, toStoredStepTime} from '@/utils/step_time_utils'

describe('toStoredStepTime', () => {
    it.each([
        [10, 60, 70, 10],
        [0, 720, 720, 0],
        [45, 0, 45, 45],
        [0, 0, 0, 0],
    ])('stores working %i / waiting %i as time %i, workingTime %i', (working, waiting, time, workingTime) => {
        expect(toStoredStepTime(working, waiting)).toEqual({time, workingTime})
    })

    it('treats missing values as no time at all', () => {
        expect(toStoredStepTime(null, undefined)).toEqual({time: 0, workingTime: 0})
        expect(toStoredStepTime(NaN, 30)).toEqual({time: 30, workingTime: 0})
        expect(toStoredStepTime(-5, 30)).toEqual({time: 30, workingTime: 0})
    })

    it('never lets the working portion exceed the total it just built', () => {
        const stored = toStoredStepTime(10, 60)
        expect(stored.workingTime).toBeLessThanOrEqual(stored.time)
    })
})

describe('fromStoredStepTime', () => {
    it.each([
        [70, 10, 10, 60],
        [720, 0, 0, 720],
        [45, 45, 45, 0],
        [0, 0, 0, 0],
    ])('reads time %i / workingTime %i as working %i, waiting %i', (time, workingTime, working, waiting) => {
        expect(fromStoredStepTime(time, workingTime)).toEqual({working, waiting})
    })

    it('reads a legacy step with only an elapsed time as fully unattended', () => {
        expect(fromStoredStepTime(720, undefined)).toEqual({working: 0, waiting: 720})
        expect(fromStoredStepTime(10, null)).toEqual({working: 0, waiting: 10})
    })

    it('clamps a working time that exceeds the total rather than emitting a negative wait', () => {
        expect(fromStoredStepTime(30, 100)).toEqual({working: 30, waiting: 0})
    })

    it('treats missing and nonsensical values as no time at all', () => {
        expect(fromStoredStepTime(null, null)).toEqual({working: 0, waiting: 0})
        expect(fromStoredStepTime(NaN, NaN)).toEqual({working: 0, waiting: 0})
        expect(fromStoredStepTime(-30, -5)).toEqual({working: 0, waiting: 0})
    })

    it('never emits a negative value', () => {
        for (const [time, workingTime] of [[70, 10], [0, 50], [30, 100], [-1, -1], [720, 0]]) {
            const {working, waiting} = fromStoredStepTime(time, workingTime)
            expect(working).toBeGreaterThanOrEqual(0)
            expect(waiting).toBeGreaterThanOrEqual(0)
        }
    })
})

describe('the conversion round trip', () => {
    it.each([
        [10, 60],
        [0, 720],
        [45, 0],
        [0, 0],
        [5, 4320],
    ])('survives working %i / waiting %i unchanged', (working, waiting) => {
        const {time, workingTime} = toStoredStepTime(working, waiting)
        expect(fromStoredStepTime(time, workingTime)).toEqual({working, waiting})
    })

    it('survives a stored pair unchanged', () => {
        for (const [time, workingTime] of [[70, 10], [720, 0], [45, 45], [0, 0]]) {
            const {working, waiting} = fromStoredStepTime(time, workingTime)
            expect(toStoredStepTime(working, waiting)).toEqual({time, workingTime})
        }
    })
})
