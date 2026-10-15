import type {AssemblyStep} from './guide'
import type {Figure} from './buildContent'

const step=(id:string,title:string,instructions:string[],check:string,chapter='Touch sensors'):AssemblyStep=>({id,chapter,title,pages:[],instructions,check})
export const TOUCH_STEPS:AssemblyStep[]=[
 step('touch-parts','Prepare the Touch sensor kit',[
  'Lay out the five Paxini sensors: one thumb, three middle-size sensors for index/middle/ring, and one pinky sensor.',
  'Lay out three 130 mm connector cables, two 280 mm connector cables, 0.2 mm copper wire, the connector board and its 4-wire cable.',
  'Sort the sensor screws by length. The four fingers use two M1.4×3 screws at each tip and two M1.4×4 at each lower fixing. The thumb uses two M1.4×4 at the tip and two M1.4×6 below. Reserve two M1.4×6 self-tapping screws for the connector board.',
 ],'I have the correct sensors, cables, wire and all three screw lengths.'),
 step('touch-ids','Assign and check the five sensor IDs',[
  'Connect the Paxini adapter to the Windows laptop and open the Paxini software. Connect only one sensor at a time.',
  'Assign IDs by finger: thumb = 0, index = 1, middle = 2, ring = 3, pinky = 4. Label each sensor so that its ID remains clear during installation.',
  'While the sensor is connected, check that it reports a response in the Paxini software. Repeat for all five sensors before installing them.',
 ],'All five sensors have the correct unique IDs and have passed the software response check.'),
 step('touch-wrap-short','Wrap the 130 mm cables',[
  'Cut approximately 50 cm of 0.2 mm copper wire for one cable. Secure its first end to the cable with a clove hitch, following the knot sequence.',
  'Wrap the wire tightly and evenly, leaving approximately 1 mm between turns. Match the pictured 130 mm cable: a roughly 3 cm wrapped section with roughly 7 cm from its end to the connector on the right of the image. Position tolerance is approximately 5 mm.',
  'Secure the other end with another clove hitch. Trim both loose wire ends to less than 2 mm. Repeat for all three 130 mm cables.',
 ],'All three short cables have even wraps, secure end knots and wire tails shorter than 2 mm.'),
 step('touch-wrap-long','Wrap the 280 mm cables',[
  'Prepare approximately 50 cm of 0.2 mm copper wire for each of the two 280 mm cables. Use the same clove-hitch start, regular 1 mm spacing and clove-hitch finish.',
  'Locate each wrap so it sits at the AP when the cable is routed. The long-cable wrap position and finger allocation have not yet been specified; establish them on the actual cable route before fixing the wrap. Do not copy the short-cable 7 cm offset onto the long cable.',
  'Trim the two wire ends to less than 2 mm. Keep the cable connectors free of wire and check that the cable insulation is undamaged.',
 ],'Both long-cable routes and wrap positions have been confirmed and the wraps are secure.'),
 step('touch-paint','Color the copper wraps',[
  'Use a black permanent marker, such as an Edding, to color the copper wire black. Keep ink away from the exposed connector contacts.',
  'Check each wrap before routing: regular turns, both end knots secure and no long wire tails.',
 ],'All five wraps are colored and checked.'),
 step('touch-route','Route the Touch cables through the hand',[
  'With power off, route the sensor cables from the bottom of the hand toward the fingertips. Follow the cable passages shown, keeping the sensor cables separate from the tendon channels.',
  'Handle the cables gently; guide the connectors through instead of pulling hard on the wires. Position each copper-wrapped section at its AP.',
  'Check the selected cable reaches its sensor and connector-board port without strain. The short/long cable allocation still needs confirmation against your kit; do not force a short cable to reach. Leave the sensor ends accessible.',
 ],'All five cables are routed gently, with the wrapped sections at the APs and enough slack to connect.'),
 step('touch-connect','Connect the cables to the Paxini sensors',[
  'Match the exposed-contact side of the sensor plug to the correct close-up. Orient the sensor exactly like the image before comparing; the wrong example shows the reversed plug.',
  'Connect the cable gently and squarely. Check it is seated in the same orientation as both correct examples; do not force a connector that does not align.',
 ],'Each sensor connector matches the correct orientation and is fully seated.'),
 step('touch-mount','Fasten the Touch sensors',[
  'Place each sensor on its matching fingertip with its assigned ID: thumb 0; index 1; middle 2; ring 3; pinky 4. Keep the cable clear of the mounting surfaces.',
  'For index, middle, ring and pinky, use two M1.4×3 screws at the tip (green) and two M1.4×4 screws at the lower fixings (blue). For the thumb, use two M1.4×4 at the tip (blue) and two M1.4×6 below (orange). Match the positions in the diagrams.',
  'Tighten gently by hand with a screwdriver; do not use power tools. These small screws can break. Confirm every sensor sits flush and that its cable is not pinched.',
 ],'All five sensors are flush, gently secured with the correct screws, and their cables are clear.'),
 step('touch-board-mount','Mount the flashed Touch connector board',[
  'Confirm the board is flashed for the selected hand side before covering its back-side programming pads. Switch power off before mounting or connecting sensors.',
  'Place the connector board in its carpal recess in the orientation shown. Secure it with two M1.4×6 self-tapping screws, tightening gently by hand.',
 ],'The flashed connector board is correctly oriented and gently secured.','Touch connector board'),
 step('touch-board-connect','Connect the Touch harness',[
  'With power off, match the correct connector-board plug orientation. The wrong example has the plug reversed; do not use wire colors alone to decide the orientation.',
  'Face the component side of the mounted board with its white 4-wire connector at the bottom: thumb is the top port; middle is upper left; index lower left; ring upper right; pinky lower right. Match the labeled board image rather than mirroring the board layout for a left hand.',
  'Connect the board to the OH board with the 4-wire cable. Keep the harness clear of the tendons, wrist joint and cover edges. Check the cables remain slack through gentle hand movement before closing the hand.',
 ],'All five sensor connections, the board cable and routing clearance are checked.','Touch connector board'),
 step('touch-test','Check the installed Touch sensors',[
  'With the assembled hand connected to the UI, confirm the selected Touch configuration reports all five sensors.',
  'Touch each sensor in turn. Confirm the expected finger responds: thumb 0, index 1, middle 2, ring 3 and pinky 4.',
  'If one is missing or assigned to the wrong finger, switch power off before checking its connector and sensor ID. Repeat the response check after correcting it.',
 ],'All five installed sensors respond at the expected fingers.','Finish'),
]

export const TOUCH_KITS:Record<string,string[]>={
 'touch-parts':['1 thumb + 3 middle-size + 1 pinky Paxini sensors','3 connector cables · 130 mm','2 connector cables · 280 mm','Copper wire · Ø0.2 mm','1 Touch connector board','1 four-wire connector-board cable','8 screws · M1.4×3','10 screws · M1.4×4','4 allocated screws · M1.4×6 (2 thumb + 2 board)','Windows laptop with Paxini software + Paxini adapter','Hand screwdriver, ruler, wire cutters, black marker'],
 'touch-ids':['5 Paxini sensors','Windows laptop with Paxini software','Paxini adapter','Labels or marker'],
 'touch-wrap-short':['3 cables · 130 mm','3 copper wire lengths · about 50 cm each, Ø0.2 mm','Ruler','Wire cutters'],
 'touch-wrap-long':['2 cables · 280 mm','2 copper wire lengths · about 50 cm each, Ø0.2 mm','Hand for checking cable paths','Ruler','Wire cutters'],
 'touch-paint':['5 wrapped cables','Black permanent marker'],
 'touch-route':['Assembled Touch hand','3 prepared 130 mm + 2 prepared 280 mm cables'],
 'touch-connect':['5 tested, ID-labeled sensors','5 routed connector cables'],
 'touch-mount':['5 connected Paxini sensors','8 screws · M1.4×3','10 screws · M1.4×4','2 screws · M1.4×6','Hand screwdriver'],
 'touch-board-mount':['Flashed Touch connector board','2 self-tapping screws · M1.4×6','Hand screwdriver'],
 'touch-board-connect':['5 routed sensor cables','Mounted Touch connector board','1 four-wire connector-board cable','OH board'],
 'touch-test':['Completed Touch hand','12 V supply','USB-C data cable','ORCA UI'],
}
const photo=(name:string,caption:string,instruction:number):Figure=>({src:`./assembly/touch/${name}.png`,caption,instruction})
export const TOUCH_FIGURES:Record<string,Figure[]>={
 'touch-parts':[photo('parts-sensors','Five Paxini sensors and copper wire',1),photo('parts-cables','Three short and two long cables, connector board and board cable',2)],
 'touch-wrap-short':[photo('clove-hitch','Clove hitch: follow the sequence from upper left to lower right',1),photo('wrap-start','Secure the first copper-wire end',1),photo('wrap-short','130 mm cable · approximately 3 cm wrap and 7 cm to the pictured right connector',2)],
 'touch-wrap-long':[photo('clove-hitch','Use a clove hitch to secure each wire end',1)],
 'touch-paint':[photo('paint-before','Copper wrap before coloring',1),photo('paint-after','Copper wrap colored black',1)],
 'touch-route':[photo('route-thumb','Cable route into the thumb',1),photo('route-finger','Cable route through a finger; the wrap sits at the AP',2)],
 'touch-connect':[photo('sensor-plug-face','Correct exposed-contact face of the sensor plug',1),photo('sensor-correct','Correct · sensor connector orientation',2),photo('sensor-correct-angle','Correct · seated connector viewed from the side',2),photo('sensor-wrong','Wrong · reversed sensor connector',2)],
 'touch-mount':[photo('sensor-seat','Cable seated beneath the sensor',1),photo('screws-fingers','Finger screw map · green M1.4×3, blue M1.4×4',2),photo('screws-thumb','Thumb screw map · blue M1.4×4, orange M1.4×6',2),photo('sensor-flush','Sensor sits flush on the fingertip',3)],
 'touch-board-mount':[photo('board-mount','Connector board seated in the carpals',2)],
 'touch-board-connect':[photo('board-correct','Correct · connector-board plug orientation',1),photo('board-wrong','Wrong · reversed connector-board plug',1),photo('board-map','Mounted board: T thumb, M middle, I index, R ring, P pinky',2)],
}
