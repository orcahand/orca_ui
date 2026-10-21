export const FINGERS=['Index','Middle','Ring','Pinky']
export const MOVEMENTS=[['DP flex','The fingertip bends toward the palm.'],['DP ext','The fingertip straightens away from the palm.'],['PP flex','The PP joint bends toward the palm.'],['PP ext','The PP joint straightens away from the palm.'],['AP p','The finger moves sideways toward the pinky.'],['AP t','The finger moves sideways toward the thumb.']]
export const FINGER_CHECKS=FINGERS.map(f=>`${f}: all six tendons move the correct joint freely, in both directions.`)
