import {describe, expect, it} from 'vitest'
import {formatDuration} from '@/utils/duration_utils'

const LABELS = {hour: 'h', minute: 'min'}

describe('formatDuration', () => {
    it.each([
        [45, '45 min'],
        [59, '59 min'],
        [60, '1 h'],
        [90, '1 h 30 min'],
        [120, '2 h'],
        [150, '2 h 30 min'],
        [4320, '72 h'],
    ])('renders %i minutes as "%s"', (minutes, expected) => {
        expect(formatDuration(minutes, LABELS)).toBe(expected)
    })

    it('renders zero as minutes', () => {
        expect(formatDuration(0, LABELS)).toBe('0 min')
    })

    it.each([null, undefined])('renders a missing duration (%s) as nothing', (minutes) => {
        expect(formatDuration(minutes, LABELS)).toBe('')
    })

    it('does not throw on negative or non finite input', () => {
        expect(formatDuration(-5, LABELS)).toBe('-5 min')
        expect(formatDuration(-90, LABELS)).toBe('-90 min')
        expect(formatDuration(NaN, LABELS)).toBe('')
        expect(formatDuration(Infinity, LABELS)).toBe('Infinity min')
    })

    it('uses the labels it is given rather than inlined units', () => {
        expect(formatDuration(150, {hour: 'Std', minute: 'Min'})).toBe('2 Std 30 Min')
        expect(formatDuration(45, {hour: 'Std', minute: 'Min'})).toBe('45 Min')
    })

    it('defaults to readable english output', () => {
        expect(formatDuration(150)).toBe('2 h 30 min')
    })

    // the formatting is unconditional: there is no preference, and no argument that puts the raw
    // minute rendering back. A second required parameter, or an ignored one that changed the
    // output, would both mean the toggle had grown back
    it('offers no way to get the raw minute rendering back', () => {
        expect(formatDuration.length).toBe(1)

        const callAnyway = formatDuration as unknown as (...args: unknown[]) => string
        expect(callAnyway(150, LABELS, false)).toBe('2 h 30 min')
        expect(callAnyway(4320, LABELS, false, {useReadableTime: false})).toBe('72 h')
    })
})
