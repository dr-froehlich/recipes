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
        expect(formatDuration(minutes, true, LABELS)).toBe(expected)
    })

    it.each([
        [45, '45 min'],
        [59, '59 min'],
        [60, '60 min'],
        [90, '90 min'],
        [120, '120 min'],
        [150, '150 min'],
        [4320, '4320 min'],
    ])('returns the raw minute form for %i with the preference off', (minutes, expected) => {
        expect(formatDuration(minutes, false, LABELS)).toBe(expected)
    })

    it('renders zero as minutes with either preference', () => {
        expect(formatDuration(0, true, LABELS)).toBe('0 min')
        expect(formatDuration(0, false, LABELS)).toBe('0 min')
    })

    it.each([null, undefined])('renders a missing duration (%s) as nothing', (minutes) => {
        expect(formatDuration(minutes, true, LABELS)).toBe('')
        expect(formatDuration(minutes, false, LABELS)).toBe('')
    })

    it('does not throw on negative or non finite input', () => {
        expect(formatDuration(-5, true, LABELS)).toBe('-5 min')
        expect(formatDuration(-90, true, LABELS)).toBe('-90 min')
        expect(formatDuration(-90, false, LABELS)).toBe('-90 min')
        expect(formatDuration(NaN, true, LABELS)).toBe('')
        expect(formatDuration(Infinity, true, LABELS)).toBe('Infinity min')
    })

    it('uses the labels it is given rather than inlined units', () => {
        expect(formatDuration(150, true, {hour: 'Std', minute: 'Min'})).toBe('2 Std 30 Min')
        expect(formatDuration(45, false, {hour: 'Std', minute: 'Min'})).toBe('45 Min')
    })

    it('defaults to readable english output', () => {
        expect(formatDuration(150)).toBe('2 h 30 min')
    })
})
