import type {AssemblyStep} from './guide'
import type {Figure} from './buildContent'

export const TOUCH_CABLE_LENGTHS=[
 {finger:'Thumb',length:280},
 {finger:'Index',length:130},
 {finger:'Middle',length:130},
 {finger:'Ring',length:280},
 {finger:'Pinky',length:130},
]

const step=(id:string,title:string,instructions:string[],check:string,chapter='Touch sensors'):AssemblyStep=>({id,chapter,title,pages:[],instructions,check})
export const TOUCH_STEPS:AssemblyStep[]=[
 step('touch-parts','Prepare the Touch sensor kit',[
  'Sort the five sensors: thumb, three middle-size sensors (index, middle and ring), and pinky. Touch uses sensors instead of DP skins.',
  'Lay out the three 130 mm cables, two 280 mm cables, copper wire, connector board and 4-wire board cable.',
  'Sort the M1.4 screws into 3, 4 and 6 mm lengths. The fastening steps show where each length goes.',
 ],'I have the correct sensors, cables, wire and all three screw lengths.'),
 step('touch-ids','Assign and check the five sensor IDs',[
  'Open the Paxini software on Windows and connect its adapter. Plug in one sensor at a time.',
  'Assign the finger ID from the table and label the sensor.',
  'Touch the sensor and check its response in the software. Repeat for all five.',
 ],'All five sensors have the correct unique IDs and have passed the software response check.'),
 step('touch-wrap-short','Wrap the 130 mm cables',[
  'Prepare the three 130 mm cables for the index, middle and pinky fingers. Cut about 50 cm of Ø0.2 mm copper wire per cable. Tie its first end to the cable with the clove hitch shown below.',
  'Wind evenly with a gap of 1 mm or less between turns. Match the 3 cm wrap and 7 cm offset to the right-hand connector (±5 mm).',
  'Finish with a clove hitch and trim both wire tails below 2 mm. Repeat for all three short cables.',
 ],'All three short cables have even wraps, secure end knots and wire tails shorter than 2 mm.'),
 step('touch-wrap-long','Wrap the 280 mm cables',[
  'Prepare the two 280 mm cables for the thumb and ring finger. Use about 50 cm of Ø0.2 mm wire per cable. Tie a clove hitch at each end of the wrap, with a gap of 1 mm or less between turns.',
  'Trial-route each cable so its wrap sits at the AP. The long-cable offset is unspecified; use the actual route rather than the short-cable 7 cm offset.',
  'Trim wire tails below 2 mm. Keep wire off the connectors and check the insulation.',
 ],'Both long-cable routes and wrap positions have been confirmed and the wraps are secure.'),
 step('touch-paint','Color the copper wraps',[
  'Color the copper wraps with a black permanent marker. Keep ink off the connector contacts.',
  'Check even turns, secure knots and short wire tails.',
 ],'All five wraps are colored and checked.'),
 step('touch-route','Route the cables through the fingers',[
  'Match each cable to its finger using the overview above. With power off, feed each cable from the hand base through the carpals and toward its fingertip using the pictured cable passages.',
  'Guide the connectors through gently and seat each copper wrap at its AP.',
  'Leave each fingertip plug accessible and its connector-board end free at the carpals, with enough slack to connect.',
 ],'All five cables are routed gently, with the wrapped sections at the APs and enough slack to connect.'),
 step('touch-skins','Fit the finger and thumb PP skins',[
  'Check that all five cables are routed and lie in their cable channels. Leave the fingertip plugs disconnected and accessible, and keep the connector-board cable tails and tendon ends accessible.',
  'Fit the matching PP skin to the index, middle, ring, pinky and thumb. Guide it into place without pulling on a connector or trapping a cable. Touch has no DP skins. Keep each fingertip plug accessible for connecting its sensor next.',
  'Seat the skin edges and gently move every finger and the thumb through their free movement. Check that no skin rubs a joint or pulls a cable. Repeat the six-tendon finger checks and eight-tendon thumb check after fitting the skins.',
 ],'All five PP skins are seated; cables are free and every finger and thumb moves freely.'),
 step('touch-connect','Connect the cables to the Paxini sensors',[
  'With the hand assembled, its finger and thumb PP skins fitted and power off, match each sensor and exposed plug contacts to the correct close-up. Connect the fingertip ends now.',
  'Insert the plug squarely and gently. Check its orientation against the correct and reversed examples.',
 ],'Each sensor connector matches the correct orientation and is fully seated.'),
 step('touch-mount','Fasten the Touch sensors',[
  'Place each labeled sensor on its matching bare DP, keeping the cable clear of the mounting surfaces. Touch uses this sensor instead of a DP skin. The PP skins should already be fitted; keep their edges clear of the sensor and cable.',
  'Fit the screws shown: fingers use two M1.4×3 at the tip and two M1.4×4 below; the thumb uses two M1.4×4 at the tip and two M1.4×6 below.',
  'Tighten gently with a hand screwdriver. Check that each sensor sits flush and its cable is free.',
 ],'All five sensors are flush, gently secured with the correct screws, and their cables are clear.'),
 step('touch-board-mount','Mount the flashed Touch connector board',[
  'Flash the board for your hand side before mounting it. Switch power off.',
  'Seat the board as pictured and secure it gently with two M1.4×6 self-tapping screws.',
 ],'The flashed connector board is correctly oriented and gently secured.','Touch connector board'),
 step('touch-board-connect','Connect the five finger cables',[
  'With power off, match each plug to the correct orientation pictured.',
  'With the white 4-wire connector at the bottom, connect the fingers to the labeled ports. The physical port map is the same for left and right hands.',
  'Check that each finger cable reaches its socket without strain and is clear of the tendons and joints.',
 ],'All five finger cables are correctly oriented, seated and connected to their labeled ports.','Touch connector board'),
 step('touch-board-cable','Prepare the connector-board cable',[
  'Carefully remove the heat-shrink tubing at one end of the four-wire cable. Work slowly and cut only the tubing, keeping the cable strands and their insulation intact.',
  'Repeat at the other end. Match the prepared cable shown, with the individual wires visible between the braided sleeve and each connector.',
  'Inspect all four wires at both ends. Confirm that the strands and insulation are undamaged and each wire is securely seated in its connector.',
 ],'The heat-shrink tubing is removed from both ends, and all cable strands, insulation and connections are intact.','Touch connector board'),
 step('touch-board-link','Connect the Touch board to the OH board',[
  'Keep board power off. Remove the rear hull cover if it is fitted and support the cover and OH board without pulling on the existing cables.',
  'Connect the prepared four-wire board cable to the white four-pin socket on the Touch connector board and the four-pin connector-board socket on the OH board. Match the keyed housings shown below; do not force or offset a plug.',
  'Follow the pictured cable route from the carpals past the wrist toward the OH board, keeping clear of the wrist belt, tendons and motor spools. At the rear cover, use the upper-right cable exit alongside the motor lead, as shown when fitting the OH board. Leave slack for wrist movement and for lifting the rear cover.',
  'Gently move the unpowered wrist through its free movement and lift the rear cover slightly. Check that neither connector is pulled, the cable cannot enter a moving part and the cover closes without pinching it.',
 ],'Both ends of the four-wire board cable are fully seated, with slack and clearance checked.','Touch connector board'),
 step('touch-carpal-cover','Mount the carpal cover',[
  'Position the matching carpal cover over the connected Touch board. Guide the cables through the cover opening and keep them clear of its edges and mounting holes.',
  'Seat the cover and align all four mounting holes. Fit four self-tapping M1.4×6 screws and tighten gently with a hand screwdriver.',
  'Check that the cover sits flush, the cables are free and the wrist moves freely.',
 ],'The carpal cover is seated and secured with four screws, and the cables and wrist move freely.','Touch connector board'),
 step('touch-test','Check the installed Touch sensors',[
  'With the assembled hand connected to the UI, confirm the selected Touch configuration reports all five sensors.',
  'Touch each sensor in turn. Confirm the expected finger responds: thumb 0, index 1, middle 2, ring 3 and pinky 4.',
  'If one is missing or assigned to the wrong finger, switch power off before checking its connector and sensor ID. Repeat the response check after correcting it.',
 ],'All five installed sensors respond at the expected fingers.','Finish'),
]

export const TOUCH_KITS:Record<string,string[]>={
 'touch-parts':['1 thumb + 3 middle-size + 1 pinky Paxini sensors','3 connector cables (130 mm)','2 connector cables (280 mm)','Copper wire (Ø0.2 mm)','1 Touch connector board','1 four-wire connector-board cable','8 screws (M1.4×3)','10 screws (M1.4×4)','2 thumb screws (M1.4×6)','6 self-tapping screws (M1.4×6; 2 board + 4 carpal cover)','Windows laptop with Paxini software + Paxini adapter','Hand screwdriver, ruler, wire cutters, black marker'],
 'touch-ids':['5 Paxini sensors','Windows laptop with Paxini software','Paxini adapter','Labels or marker'],
 'touch-wrap-short':['3 cables (130 mm)','3 copper wire lengths (about 50 cm each, Ø0.2 mm)','Ruler','Wire cutters'],
 'touch-wrap-long':['2 cables (280 mm)','2 copper wire lengths (about 50 cm each, Ø0.2 mm)','Assembled hand for checking cable paths','Ruler','Wire cutters'],
 'touch-paint':['5 wrapped cables','Black permanent marker'],
 'touch-route':['Assembled hand and wrist','3 prepared cables (130 mm; index, middle and pinky)','2 prepared cables (280 mm; thumb and ring)'],
 'touch-connect':['5 tested, ID-labeled sensors','Assembled hand with routed cables and fitted finger and thumb PP skins'],
 'touch-mount':['5 connected Paxini sensors','8 screws (M1.4×3)','10 screws (M1.4×4)','2 screws (M1.4×6)','Hand screwdriver'],
 'touch-skins':['Assembled hand with routed, disconnected sensor cables','Matching index, middle, ring, pinky and thumb PP skins'],
 'touch-board-mount':['Flashed Touch connector board','2 self-tapping screws (M1.4×6)','Hand screwdriver'],
 'touch-board-connect':['5 routed sensor cables','Mounted Touch connector board'],
 'touch-board-cable':['1 four-wire connector-board cable'],
 'touch-board-link':['Mounted Touch connector board','OH board in its rear cover','1 prepared four-wire connector-board cable'],
 'touch-carpal-cover':['Matching carpal cover','4 self-tapping screws (M1.4×6)'],
 'touch-test':['Completed Touch hand','12 V supply','USB-C data cable','ORCA UI'],
}
const photo=(name:string,caption:string,instruction:number):Figure=>({src:`./assembly/touch/${name}.webp`,caption,instruction,showCaption:/correct|wrong|paint-|board-map|clove-hitch/.test(name)})
export const TOUCH_FIGURES:Record<string,Figure[]>={
 'touch-parts':[photo('parts-sensors','Five Paxini sensors and copper wire',1),photo('parts-cables','Three short and two long cables, connector board and board cable',2)],
 'touch-wrap-short':[],
 'touch-wrap-long':[],
 'touch-paint':[photo('paint-before','Copper wrap before coloring',1),photo('paint-after','Copper wrap colored black',1)],
 'touch-route':[photo('route-thumb','Cable route into the thumb',1),photo('route-finger','Cable route through a finger; the wrap sits at the AP',2)],
 'touch-connect':[photo('sensor-plug-face','Correct exposed-contact face of the sensor plug',1),photo('sensor-correct','Correct (sensor connector orientation)',2),photo('sensor-correct-angle','Correct (seated connector viewed from the side)',2),photo('sensor-wrong','Wrong (reversed sensor connector)',2)],
 'touch-mount':[photo('sensor-seat','Cable seated beneath the sensor',1),photo('sensor-flush','Sensor sits flush on the fingertip',3)],
 'touch-board-mount':[photo('board-mount','Connector board seated in the carpals',2)],
 'touch-board-connect':[photo('board-correct','Correct (connector-board plug orientation)',1),photo('board-wrong','Wrong (reversed connector-board plug)',1),photo('board-map','Mounted board: T thumb, M middle, I index, R ring, P pinky',2)],
 'touch-board-cable':[
  {src:'./assembly/touch/board-cable-end.jpg',caption:'Cable end before and after careful removal of the heat-shrink tubing',instruction:1,showCaption:true},
  {src:'./assembly/touch/board-cable-preparation.jpg',caption:'Remove the heat-shrink tubing at both ends, keeping all four wires intact',instruction:2,showCaption:true},
 ],
 'touch-board-link':[
  {src:'./assembly/touch/board-cable-routing-wrist.png',caption:'Cable route from the Touch connector board past the wrist',instruction:3,showCaption:true},
  {src:'./assembly/touch/board-cable-routing-overview.jpg',caption:'Cable route toward the OH board with the rear cover open',instruction:3,showCaption:true},
 ],
}
